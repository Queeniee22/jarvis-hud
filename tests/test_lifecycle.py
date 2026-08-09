"""Resource lifecycle: what happens on cancellation and shutdown.

Every bug here was invisible in normal operation and only showed up as a
leaked process, a claimed microphone, or a service that quietly stopped.
"""
import asyncio

import pytest


class StubHub:
    def __init__(self):
        self.msgs = []

    async def broadcast(self, m):
        self.msgs.append(m)


async def test_cancelling_a_turn_kills_the_claude_process(monkeypatch):
    """Re-raising CancelledError without killing the child left an orphaned
    Node process behind for every cancelled turn."""
    from jarvis.services import brain

    killed = {"n": 0}

    class FakeProc:
        returncode = None
        def __init__(self):
            self.stdout = self
            self.stderr = self
        async def read(self):
            return b""
        def __aiter__(self):
            return self
        async def __anext__(self):
            await asyncio.sleep(3600)  # hang, so the task can be cancelled
            raise StopAsyncIteration
        def kill(self):
            killed["n"] += 1
            FakeProc.returncode = 0
        async def wait(self):
            return 0

    proc = FakeProc()

    async def fake_exec(*a, **k):
        return proc

    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_exec)
    monkeypatch.setattr(brain, "iter_lines", lambda stdout: proc)

    hub = StubHub()
    task = asyncio.create_task(brain.ask(hub, "hello"))
    await asyncio.sleep(0.05)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    assert killed["n"] >= 1, "a cancelled turn must not orphan the subprocess"


async def test_cancelled_turn_does_not_start_speaking(monkeypatch):
    """The finally block used to emit and queue TTS even while shutting
    down, scheduling work onto a loop that was going away."""
    from jarvis.services import brain, voice

    spoke = {"n": 0}

    async def fake_speak(hub, text):
        spoke["n"] += 1

    monkeypatch.setattr(voice, "speak", fake_speak)

    class FakeProc:
        returncode = None
        def __init__(self):
            self.stdout = self
            self.stderr = self
        async def read(self):
            return b""
        def __aiter__(self):
            return self
        async def __anext__(self):
            await asyncio.sleep(3600)
            raise StopAsyncIteration
        def kill(self):
            FakeProc.returncode = 0
        async def wait(self):
            return 0

    proc = FakeProc()
    monkeypatch.setattr(asyncio, "create_subprocess_exec", lambda *a, **k: _wrap(proc))
    monkeypatch.setattr(brain, "iter_lines", lambda stdout: proc)

    hub = StubHub()
    task = asyncio.create_task(brain.ask(hub, "hello", source="voice"))
    await asyncio.sleep(0.05)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    await asyncio.sleep(0.05)

    assert spoke["n"] == 0, "a cancelled turn must not start speaking"


async def _wrap(proc):
    return proc


async def test_shutdown_cancels_services_and_does_not_hang():
    """Services were spawned with no reference and never cancelled, so
    shutdown left them running."""
    from jarvis import app as app_mod

    started = {"n": 0}

    async def forever():
        started["n"] += 1
        while True:
            await asyncio.sleep(3600)

    task = app_mod._spawn(forever())
    await asyncio.sleep(0.02)
    assert task in app_mod._service_tasks, "the task must be referenced, not left to the GC"

    await asyncio.wait_for(app_mod._shutdown(), timeout=5)
    assert task.cancelled() or task.done()


def test_spawn_keeps_a_strong_reference():
    """asyncio keeps only weak references; a discarded task object can be
    collected mid-run and the service simply stops."""
    from jarvis import app as app_mod
    import inspect

    src = inspect.getsource(app_mod._spawn)
    assert "_service_tasks.add" in src
    assert "add_done_callback" in src, "must not leak entries after completion"
