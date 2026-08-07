import asyncio
import logging

import numpy as np
import requests

from jarvis import config

log = logging.getLogger(__name__)

TTS_URL = "https://api.elevenlabs.io/v1/text-to-speech/{voice_id}"
MODEL_ID = "eleven_turbo_v2_5"
SAMPLERATE = 16000
FRAME_SEC = 0.1

# Overlapping speak() calls are serialized behind this lock rather than
# interrupting each other with sd.stop(). Jarvis says one reply at a time,
# in order; queueing is simpler and avoids a race where an old call's
# trailing "inactive" broadcast could stomp a new call's "active" frames.
_lock = asyncio.Lock()


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
        json={"text": text, "model_id": MODEL_ID},
        timeout=30,
    )
    r.raise_for_status()
    return np.frombuffer(r.content, dtype=np.int16).astype("float32") / 32768.0


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

    async with _lock:
        try:
            pcm = await asyncio.to_thread(_fetch_pcm, text)
        except Exception as e:
            log.warning("voice: tts fetch failed: %s", e)
            await hub.broadcast({"type": "status", "service": "voice", "state": "error", "detail": str(e)})
            return

        try:
            sd.play(pcm, SAMPLERATE)
            for lvl in frame_levels(pcm, SAMPLERATE, FRAME_SEC):
                await hub.broadcast({"type": "speak", "level": lvl, "active": True})
                await asyncio.sleep(FRAME_SEC)
        except Exception as e:
            # speak() is fired and forgotten by brain.ask(), so an escaping
            # exception here would die silently in the task. Report it.
            log.warning("voice: playback failed: %s", e)
            await hub.broadcast({"type": "status", "service": "voice", "state": "error", "detail": str(e)})
        finally:
            await hub.broadcast({"type": "speak", "level": 0.0, "active": False})
