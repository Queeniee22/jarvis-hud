import asyncio
import numpy as np

_muted = False


def is_muted() -> bool:
    return _muted


def set_muted(v: bool):
    global _muted
    _muted = v


def rms_level(block) -> float:
    rms = float(np.sqrt(np.mean(np.square(block))))
    return max(0.0, min(1.0, rms * 3.0))


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
    while True:
        block = await q.get()
        buffer.append(block)
        if len(buffer) >= 20:  # ~2s at 1600-sample blocks
            audio = np.concatenate(buffer)[:, 0]
            buffer = []

            def _transcribe(audio=audio):
                segments, _ = model.transcribe(audio, language="en")
                return " ".join(s.text for s in segments).strip()

            try:
                text = await loop.run_in_executor(None, _transcribe)
            except Exception:
                text = ""
            if text:
                await hub.broadcast({"type": "chat", "role": "you", "delta": text, "done": True})
                from jarvis.services import brain
                asyncio.create_task(brain.ask(hub, text))
