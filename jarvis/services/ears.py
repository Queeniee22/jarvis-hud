import asyncio
import logging

import numpy as np

log = logging.getLogger(__name__)

_muted = False


def is_muted() -> bool:
    return _muted


def set_muted(v: bool):
    global _muted
    _muted = v


# Measured on Mackenzie's Fifine: room noise ~0.0004, speech peak-frame
# ~0.0084. 0.003 sits ~7x above the noise floor and ~3x below normal
# speech, so quiet or distant talking still registers.
SPEECH_RMS_THRESHOLD = 0.003
_GATE_FRAME = 1600  # 0.1s at 16kHz


def has_speech(audio, threshold: float = SPEECH_RMS_THRESHOLD) -> bool:
    """True if `audio` carries speech-level energy, not just room noise.

    Guards the transcriber: faster-whisper asked to transcribe silence
    reliably invents short phrases, which would otherwise be posted to the
    chat as if the user had said them.

    Measured on the LOUDEST 0.1s frame rather than the mean over the whole
    chunk. A chunk is ~2s and normal speech leaves most of it near-silent,
    so a mean would dilute real words below the threshold on a quiet mic
    and discard them.
    """
    if len(audio) == 0:
        return False
    peak = 0.0
    for start in range(0, len(audio), _GATE_FRAME):
        frame = audio[start:start + _GATE_FRAME]
        if len(frame) == 0:
            continue
        peak = max(peak, float(np.sqrt(np.mean(np.square(frame)))))
    return peak >= threshold


# Visual gain for the pink waveform. A gain of 3 was calibrated for a hot
# mic; on Mackenzie's Fifine, speech RMS ~0.0084 rendered bars at 2.5%
# height -- the visualizer looked dead while the mic was in fact working.
# 25 maps her room noise (~0.0004) to a flat ~1%, normal speech to ~20%,
# and loud speech (~0.04) to full height.
MIC_VIS_GAIN = 25.0

# Utterance endpointing, in 0.1s blocks. The old loop transcribed on a fixed
# 2s boundary, so it sat waiting even after you'd clearly stopped talking,
# and could also slice a sentence in half. Now a pause ends the utterance.
END_SILENCE_BLOCKS = 6      # 0.6s of quiet = you're done talking
PREROLL_BLOCKS = 3          # 0.3s kept before speech so the first syllable survives
MAX_UTTERANCE_BLOCKS = 150  # 15s hard cap so a noisy room can't buffer forever


def rms_level(block) -> float:
    rms = float(np.sqrt(np.mean(np.square(block))))
    return max(0.0, min(1.0, rms * MIC_VIS_GAIN))


_mic_broadcast_task = None


def _schedule_mic(loop, hub, msg):
    """Marshal a mic-level broadcast, coalescing bursts.

    The audio callback fires ~10x/sec. If we blindly create_task() a
    broadcast on every callback, a slow client can leave several
    broadcasts in flight concurrently, which drives concurrent
    ws.send_json() calls on the same socket (invalid) and can spin the
    event loop. Instead, drop a frame if the previous mic broadcast
    hasn't finished yet -- amplitude is a live signal, so losing a
    stale frame is harmless.
    """
    def _go():
        global _mic_broadcast_task
        if _mic_broadcast_task is None or _mic_broadcast_task.done():
            _mic_broadcast_task = asyncio.create_task(hub.broadcast(msg))
    loop.call_soon_threadsafe(_go)


async def run(hub):
    try:
        import sounddevice as sd
        from faster_whisper import WhisperModel
    except Exception as e:
        await hub.broadcast({"type": "status", "service": "ears", "state": "offline", "detail": f"import: {e}"})
        return

    try:
        model = WhisperModel("small", device="cpu", compute_type="int8")
    except Exception as e:
        await hub.broadcast({"type": "status", "service": "ears", "state": "offline", "detail": f"model: {e}"})
        return

    loop = asyncio.get_event_loop()
    # Bounded to ~5s of audio (50 blocks x 100ms). If transcription of a
    # chunk takes longer than the chunk itself, an unbounded queue would
    # grow forever and transcription would permanently lag behind live
    # audio. Instead we drop the oldest queued block to keep latency
    # bounded -- losing a little audio is better than an ever-growing
    # backlog.
    q: asyncio.Queue = asyncio.Queue(maxsize=50)

    def _enqueue(block):
        if q.full():
            try:
                q.get_nowait()  # drop oldest to make room
            except asyncio.QueueEmpty:
                pass
        q.put_nowait(block)

    def cb(indata, frames, t, status):
        lvl = 0.0 if _muted else rms_level(indata[:, 0])
        _schedule_mic(loop, hub, {"type": "mic", "level": lvl, "muted": _muted})
        if not _muted:
            loop.call_soon_threadsafe(_enqueue, indata.copy())

    try:
        stream = sd.InputStream(channels=1, samplerate=16000, blocksize=1600, callback=cb)
        stream.start()
    except Exception as e:
        await hub.broadcast({"type": "status", "service": "ears", "state": "offline", "detail": f"device: {e}"})
        return

    buffer = []
    speaking = False
    silent_run = 0
    while True:
        block = await q.get()
        block_has_speech = has_speech(block[:, 0])

        if block_has_speech:
            speaking = True
            silent_run = 0
            buffer.append(block)
        elif speaking:
            # Keep trailing silence: it carries the tail of the last word
            # and helps the transcriber close the utterance cleanly.
            silent_run += 1
            buffer.append(block)
        else:
            # Not talking yet. Hold a short pre-roll so the first syllable
            # isn't clipped when speech does start.
            buffer.append(block)
            if len(buffer) > PREROLL_BLOCKS:
                buffer.pop(0)
            continue

        utterance_over = silent_run >= END_SILENCE_BLOCKS
        too_long = len(buffer) >= MAX_UTTERANCE_BLOCKS
        if not (utterance_over or too_long):
            continue

        audio = np.concatenate(buffer)[:, 0]
        buffer = []
        speaking = False
        silent_run = 0

        # Silence gate: Whisper hallucinates on near-silent audio
        # (classically "Thank you." / "you"), which would post phantom
        # messages to the chat and wake the brain. Only transcribe a
        # chunk that actually contains speech-level energy.
        if not has_speech(audio):
            continue

        def _transcribe(audio=audio):
            segments, _ = model.transcribe(
                audio, language="en", vad_filter=True
            )
            return " ".join(s.text for s in segments).strip()

        try:
            text = await loop.run_in_executor(None, _transcribe)
        except Exception:
            log.exception("ears: transcription failed")
            text = ""
        if text:
            # Spoken turns stay out of the chat panel entirely -- no
            # transcript of what you said, no text reply. Jarvis just
            # answers out loud. Typed turns still show text.
            log.info("ears: heard %r", text)
            # Its own message type, not a chat message: the HUD shows
            # this as a brief fading caption under the waveform so a
            # misheard phrase is visible, without putting a transcript
            # in the chat panel.
            await hub.broadcast({"type": "heard", "text": text})
            from jarvis.services import brain
            asyncio.create_task(brain.ask(hub, text, source="voice"))
