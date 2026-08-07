import asyncio
import logging
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


async def _prewarm_one(phrase: str):
    if phrase in _ack_cache:
        return
    try:
        _ack_cache[phrase] = await asyncio.to_thread(_fetch_pcm, phrase)
    except Exception as e:
        log.warning("voice: could not prewarm ack %r: %s", phrase, e)


async def prewarm_acks():
    """Synthesize the filler phrases once, at startup.

    Without this the first acknowledgement pays a ~0.6s TTS fetch, which is
    exactly the dead air it exists to cover.
    """
    if not available():
        return
    for phrase in ACK_PHRASES:
        await _prewarm_one(phrase)
    log.info("voice: prewarmed %d ack phrases", len(_ack_cache))


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
        await _prewarm_one(phrase)
    pcm = _ack_cache.get(phrase)
    if pcm is None:
        return
    await _play(hub, pcm)


async def _play(hub, pcm):
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
            sd.play(pcm, SAMPLERATE)
            for lvl in frame_levels(pcm, SAMPLERATE, FRAME_SEC):
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


async def speak(hub, text: str):
    if not available():
        await hub.broadcast({
            "type": "status", "service": "voice", "state": "offline",
            "detail": "missing ELEVENLABS_API_KEY or VOICE_ID",
        })
        return

    try:
        import sounddevice as sd
    except Exception as e:
        await hub.broadcast({"type": "status", "service": "voice", "state": "offline", "detail": f"import: {e}"})
        return

    try:
        pcm = await asyncio.to_thread(_fetch_pcm, text)
    except Exception as e:
        log.warning("voice: tts fetch failed: %s", e)
        await hub.broadcast({"type": "status", "service": "voice", "state": "error", "detail": str(e)})
        return

    await _play(hub, pcm)
