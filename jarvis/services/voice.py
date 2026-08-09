import asyncio
import logging
import os
import random
import time

import numpy as np
import requests

from jarvis import config

log = logging.getLogger(__name__)

TTS_URL = "https://api.elevenlabs.io/v1/text-to-speech/{voice_id}/stream"
MODEL_ID = "eleven_turbo_v2_5"
SAMPLERATE = 16000
FRAME_SEC = 0.1

# Overlapping speak() calls are serialized behind this lock rather than
# interrupting each other with sd.stop(). Jarvis says one reply at a time,
# in order; queueing is simpler and avoids a race where an old call's
# trailing "inactive" broadcast could stomp a new call's "active" frames.
_lock = asyncio.Lock()

# Half-duplex. There is no echo cancellation, so while Jarvis is talking the
# mic would hear Jarvis and feed his own words back into the transcriber.
# Capture is suppressed for the duration, plus a short tail for the speaker
# ringing out.
SPEAK_TAIL_SEC = 0.4
_speaking = False
_speaking_until = 0.0


def is_speaking() -> bool:
    """True while Jarvis is audible, including the post-speech tail."""
    return _speaking or time.monotonic() < _speaking_until


def stop_speaking():
    """Cut playback off mid-sentence so Mackenzie can interrupt."""
    global _speaking, _speaking_until
    try:
        import sounddevice as sd
        sd.stop()
    except Exception:
        pass
    _speaking = False
    _speaking_until = 0.0


def available() -> bool:
    return bool(config.ELEVENLABS_API_KEY) and bool(config.VOICE_ID)


def frame_levels(pcm, samplerate=16000, frame_sec=0.1) -> list:
    """RMS amplitude per frame_sec window of `pcm`, scaled to ~0..1.

    Pure function, no I/O -- used both to drive the live `speak` broadcast
    cadence and to unit test the amplitude math directly.
    """
    frame_size = max(1, int(samplerate * frame_sec))
    n = len(pcm)
    if n == 0:
        return []
    levels = []
    for start in range(0, n, frame_size):
        chunk = pcm[start:start + frame_size]
        rms = float(np.sqrt(np.mean(np.square(chunk))))
        levels.append(min(1.0, rms * 3.0))
    return levels


class QuotaExhausted(Exception):
    """ElevenLabs has no credits left this month."""


# Once the monthly quota is gone it stays gone until it resets, so there is no
# point paying a failed round-trip before every single line. Set on the first
# quota error and cleared only on restart.
_quota_gone = False


def _is_quota_error(resp) -> bool:
    """ElevenLabs reports an exhausted quota as 401 Unauthorized, which reads
    like a bad API key and sent this project looking in the wrong place. The
    body is what actually distinguishes the two."""
    if resp.status_code not in (401, 429):
        return False
    try:
        detail = resp.json().get("detail")
    except Exception:
        return False
    # `detail` is a dict for structured errors but a bare string for others
    # ("Invalid API key"). Assuming a dict turned a genuine auth failure into
    # an AttributeError inside the fetch path.
    if isinstance(detail, dict):
        haystack = f"{detail.get('status', '')} {detail.get('code', '')}"
    else:
        haystack = str(detail or "")
    return "quota" in haystack.lower()


def _local_pcm(text: str):
    """Synthesize with the Windows built-in voice. Free, offline, unlimited.

    Rendered to a file rather than spoken directly so it goes through the same
    playback path as ElevenLabs -- which is what keeps the core sphere
    reacting to it instead of the HUD looking dead while Jarvis talks.
    """
    import tempfile
    import wave

    import pyttsx3

    engine = pyttsx3.init()
    # Prefer a female voice to match the ElevenLabs one; fall back to whatever
    # the machine has rather than failing over a cosmetic preference.
    for v in engine.getProperty("voices"):
        if "zira" in v.name.lower() or "female" in str(getattr(v, "gender", "")).lower():
            engine.setProperty("voice", v.id)
            break
    engine.setProperty("rate", 175)

    path = tempfile.mktemp(suffix=".wav")
    try:
        engine.save_to_file(text, path)
        engine.runAndWait()
        with wave.open(path, "rb") as w:
            rate = w.getframerate()
            frames = w.readframes(w.getnframes())
        pcm = np.frombuffer(frames, dtype=np.int16).astype("float32") / 32768.0
        return pcm, rate
    finally:
        try:
            os.remove(path)
        except OSError:
            pass


def _fetch_pcm(text: str) -> np.ndarray:
    """Blocking HTTP call to ElevenLabs TTS -- run via asyncio.to_thread.

    Reads the API key / voice id from `config` at call time (not import
    time) so a user editing .env and restarting picks up the new voice
    without a code change.
    """
    key = config.ELEVENLABS_API_KEY
    voice_id = config.VOICE_ID
    url = TTS_URL.format(voice_id=voice_id)
    r = requests.post(
        url,
        headers={"xi-api-key": key, "accept": "audio/pcm"},
        params={"output_format": "pcm_16000"},
        json={
            "text": text,
            "model_id": MODEL_ID,
            # Lowest-latency setting: ElevenLabs starts returning audio
            # sooner at the cost of a little prosody smoothing.
            "optimize_streaming_latency": 3,
        },
        timeout=30,
    )
    if _is_quota_error(r):
        raise QuotaExhausted(
            "ElevenLabs monthly quota is used up -- speaking with the local "
            "Windows voice until it resets"
        )
    r.raise_for_status()
    return np.frombuffer(r.content, dtype=np.int16).astype("float32") / 32768.0


# Spoken the moment a voice turn starts. Kept short so they finish well
# inside the brain's ~5s turn and never collide with the real answer.
ACK_PHRASES = [
    "working on it, miss",
    "thinking now",
    "one moment, miss",
    "on it",
    "let me think",
]

_ack_cache = {}


async def _prewarm_one(hub, phrase: str):
    if phrase in _ack_cache:
        return
    pcm, rate = await synthesize(hub, phrase)
    if pcm is not None:
        _ack_cache[phrase] = (pcm, rate)


async def prewarm_acks(hub=None):
    """Synthesize the filler phrases once, at startup.

    Without this the first acknowledgement pays a ~0.6s TTS fetch, which is
    exactly the dead air it exists to cover.
    """
    for phrase in ACK_PHRASES:
        await _prewarm_one(hub, phrase)
    log.info("voice: prewarmed %d ack phrases", len(_ack_cache))
    if hub is not None:
        # Prewarming proves synthesis end-to-end, which is a better health
        # signal than merely having the settings present. "degraded" says the
        # voice works but is the local one -- distinct from both fine and dead.
        if not _ack_cache:
            state, detail = "error", "no voice available"
        elif _quota_gone or not available():
            state, detail = "degraded", "using the local Windows voice"
        else:
            state, detail = "online", None
        msg = {"type": "status", "service": "voice", "state": state}
        if detail:
            msg["detail"] = detail
        await hub.broadcast(msg)


async def speak_ack(hub):
    """Say a short filler so a slow turn doesn't sound like it was ignored.

    The Claude CLI needs ~5s per turn, almost all of it fixed startup cost
    that can't be tuned away, so without this you talk and get silence and
    wonder whether it heard you.
    """
    if not available():
        return
    phrase = random.choice(ACK_PHRASES)
    if phrase not in _ack_cache:
        await _prewarm_one(hub, phrase)
    cached = _ack_cache.get(phrase)
    if cached is None:
        return
    pcm, rate = cached
    await _play(hub, pcm, rate)


async def _play(hub, pcm, samplerate: int = SAMPLERATE):
    """Play `pcm` and stream its amplitude so the core sphere reacts."""
    try:
        import sounddevice as sd
    except Exception as e:
        await hub.broadcast({"type": "status", "service": "voice", "state": "offline", "detail": f"import: {e}"})
        return
    global _speaking, _speaking_until
    async with _lock:
        try:
            _speaking = True
            sd.play(pcm, samplerate)
            for lvl in frame_levels(pcm, samplerate, FRAME_SEC):
                if not _speaking:
                    break  # interrupted -- stop streaming amplitude too
                await hub.broadcast({"type": "speak", "level": lvl, "active": True})
                await asyncio.sleep(FRAME_SEC)
        except Exception as e:
            log.warning("voice: playback failed: %s", e)
            await hub.broadcast({"type": "status", "service": "voice", "state": "error", "detail": str(e)})
        finally:
            _speaking = False
            _speaking_until = time.monotonic() + SPEAK_TAIL_SEC
            await hub.broadcast({"type": "speak", "level": 0.0, "active": False})


async def synthesize(hub, text: str):
    """Audio for `text`, from ElevenLabs if it can, locally if it cannot.

    Returns (pcm, samplerate) or (None, None). Going quiet because a monthly
    quota ran out is a bad failure mode for an assistant you talk to -- the
    local Windows voice is worse-sounding but always available.
    """
    global _quota_gone

    if available() and not _quota_gone:
        try:
            return await asyncio.to_thread(_fetch_pcm, text), SAMPLERATE
        except QuotaExhausted as e:
            _quota_gone = True
            log.warning("voice: %s", e)
            await hub.broadcast({
                "type": "status", "service": "voice", "state": "degraded",
                "detail": str(e),
            })
        except Exception as e:
            log.warning("voice: tts fetch failed, falling back to local: %s", e)

    try:
        pcm, rate = await asyncio.to_thread(_local_pcm, text)
        return pcm, rate
    except Exception as e:
        log.warning("voice: local synthesis failed too: %s", e)
        await hub.broadcast({
            "type": "status", "service": "voice", "state": "error",
            "detail": f"no voice available: {e}",
        })
        return None, None


async def speak(hub, text: str):
    pcm, rate = await synthesize(hub, text)
    if pcm is None:
        return
    await _play(hub, pcm, rate)
