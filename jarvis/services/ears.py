import asyncio
import collections
import logging

import numpy as np

from jarvis.services import voice

log = logging.getLogger(__name__)

_muted = False

# Push-to-talk. Releasing the key IS the end of the turn, so there is no
# silence detection and nothing to guess at -- the cause of Jarvis cutting
# Mackenzie off mid-sentence.
_ptt = False
_q = None
_loop = None
_preroll = collections.deque(maxlen=3)
_FLUSH = object()


def is_ptt() -> bool:
    return _ptt


def set_ptt(active: bool) -> bool:
    """Start or stop capturing. Returns True if the state actually changed."""
    global _ptt
    active = bool(active)
    if active == _ptt:
        return False
    _ptt = active
    log.info("ears: ptt %s (queue=%s muted=%s)",
             "DOWN" if active else "UP", _q is not None, _muted)
    if _q is None or _loop is None:
        log.warning("ears: ptt ignored -- capture loop not running")
        return True
    try:
        if active:
            # Seed with the moments just before the key went down, so the
            # first syllable isn't clipped by human reaction time.
            for block in list(_preroll):
                _loop.call_soon_threadsafe(_enqueue_global, block)
        else:
            _loop.call_soon_threadsafe(_enqueue_global, _FLUSH)
    except RuntimeError:
        # The capture loop is gone (shutdown, or a restarted event loop).
        # Toggling the key must never raise into the websocket handler.
        log.debug("ears: capture loop unavailable, dropping ptt signal")
    return True


def _enqueue_global(item):
    if _q is None:
        return
    if _q.full():
        try:
            _q.get_nowait()
        except asyncio.QueueEmpty:
            pass
    _q.put_nowait(item)


def is_muted() -> bool:
    return _muted


def set_muted(v: bool):
    global _muted
    _muted = v


# Measured on Mackenzie's Fifine: room noise ~0.0004, speech peak-frame
# ~0.0084. 0.003 sits ~7x above the noise floor and ~3x below normal
# speech, so quiet or distant talking still registers.
SPEECH_RMS_THRESHOLD = 0.003

# Hysteresis. Speech has a wide dynamic range: soft syllables, trailing
# word endings and breaths between phrases all dip well under the start
# threshold, and a single fixed bar treated those dips as "he's finished"
# and cut him off mid-sentence. Once talking has begun, it takes a much
# quieter signal to count as a pause -- still comfortably above the ~0.0004
# noise floor.
CONTINUE_RMS_THRESHOLD = 0.0012

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
# Push-to-talk ended the guessing: releasing the key ends the turn, so there
# is no silence threshold to tune. Automatic endpointing cut Mackenzie off
# mid-sentence at 0.6s, 1.5s and 2.0s alike.
PREROLL_BLOCKS = 3          # 0.3s captured before the key went down
MAX_UTTERANCE_BLOCKS = 600  # 60s backstop for a key left held down


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

    global _q, _loop
    loop = asyncio.get_event_loop()
    _loop = loop
    # Bounded to ~5s of audio (50 blocks x 100ms). If transcription of a
    # chunk takes longer than the chunk itself, an unbounded queue would
    # grow forever and transcription would permanently lag behind live
    # audio. Instead we drop the oldest queued block to keep latency
    # bounded -- losing a little audio is better than an ever-growing
    # backlog.
    q: asyncio.Queue = asyncio.Queue(maxsize=400)  # ~40s of held audio
    _q = q

    def _enqueue(block):
        if q.full():
            try:
                q.get_nowait()  # drop oldest to make room
            except asyncio.QueueEmpty:
                pass
        q.put_nowait(block)

    def cb(indata, frames, t, status):
        block = indata.copy()
        _preroll.append(block)
        capturing = _ptt and not _muted
        # Show the live level only while actually capturing, so the waveform
        # means "Jarvis is hearing this" rather than "the mic exists".
        lvl = rms_level(indata[:, 0]) if capturing else 0.0
        _schedule_mic(loop, hub, {
            "type": "mic", "level": lvl, "muted": _muted,
            "ptt": bool(_ptt), "gated": bool(voice.is_speaking()),
        })
        if capturing:
            loop.call_soon_threadsafe(_enqueue, block)

    try:
        stream = sd.InputStream(channels=1, samplerate=16000, blocksize=1600, callback=cb)
        stream.start()
    except Exception as e:
        await hub.broadcast({"type": "status", "service": "ears", "state": "offline", "detail": f"device: {e}"})
        return

    # Say so when it works, not only when it breaks: a panel that shows a
    # service only on failure can't distinguish "healthy" from "never started".
    await hub.broadcast({"type": "status", "service": "ears", "state": "online"})

    try:
        await _capture_loop(hub, q, model, loop)
    finally:
        # The loop only ever exits by cancellation (shutdown). Without this
        # the PortAudio stream stays open and keeps the microphone claimed
        # for the life of the process.
        try:
            stream.stop()
            stream.close()
        except Exception:
            log.debug("ears: input stream already closed")


async def _capture_loop(hub, q, model, loop):
    buffer = []
    while True:
        item = await q.get()

        # A held key produces audio blocks; releasing it produces _FLUSH.
        # The release IS the end of the turn, so nothing here has to guess
        # whether Mackenzie has finished talking.
        if item is not _FLUSH:
            buffer.append(item)
            if len(buffer) < MAX_UTTERANCE_BLOCKS:
                continue
            log.warning("ears: hit the %ds cap, transcribing early",
                        int(MAX_UTTERANCE_BLOCKS * 0.1))

        if not buffer:
            continue
        audio = np.concatenate(buffer)[:, 0]
        buffer = []

        # Guard against an accidental tap or a press with nothing said:
        # Whisper invents phrases when handed silence.
        if not has_speech(audio):
            log.info("ears: nothing audible in that press, ignoring")
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
