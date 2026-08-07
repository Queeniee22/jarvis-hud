import asyncio
import json

import pytest

from jarvis.services import brain
from jarvis.services.brain import parse_stream_line


def test_parse_assistant_text_delta():
    line = '{"type":"assistant","message":{"content":[{"type":"text","text":"hi"}]}}'
    assert parse_stream_line(line) == "hi"


def test_parse_non_text_returns_none():
    assert parse_stream_line('{"type":"system","subtype":"init"}') is None


def test_parse_garbage_returns_none():
    assert parse_stream_line("not json") is None


def test_parse_long_line_over_default_stream_limit():
    # Default asyncio StreamReader limit is 64KB; a single assistant
    # message can legitimately exceed that. Make sure parsing (and, by
    # extension, the raised subprocess limit) handles it.
    long_text = "x" * (70 * 1024)
    line = json.dumps({
        "type": "assistant",
        "message": {"content": [{"type": "text", "text": long_text}]},
    })
    assert len(line) > 64 * 1024
    assert parse_stream_line(line) == long_text


class FakeStream:
    """Stands in for a StreamReader. `script` entries are bytes to return
    or exceptions to raise from readline()."""

    def __init__(self, script):
        self._script = list(script)

    async def readline(self):
        if not self._script:
            return b""
        item = self._script.pop(0)
        if isinstance(item, BaseException):
            raise item
        return item

    async def read(self, n=-1):
        return b""


class FakeHub:
    def __init__(self):
        self.messages = []

    async def broadcast(self, message):
        self.messages.append(message)


def test_iter_lines_skips_oversized_line_and_keeps_reading():
    # readline() raises ValueError when a line exceeds the reader's limit.
    # It has already drained the buffer by then, so the rest of the stream
    # must still come through.
    stream = FakeStream([
        b'{"type":"assistant","message":{"content":[{"type":"text","text":"a"}]}}\n',
        ValueError("Separator is found, but chunk is longer than limit"),
        b'{"type":"assistant","message":{"content":[{"type":"text","text":"b"}]}}\n',
    ])

    async def collect():
        return [line async for line in brain.iter_lines(stream)]

    lines = asyncio.run(collect())
    assert [parse_stream_line(x) for x in lines] == ["a", "b"]


def test_iter_lines_gives_up_on_a_stream_that_never_drains():
    # A stream that raises forever without consuming would spin the event
    # loop, since the error path never awaits. Bail instead of wedging.
    stream = FakeStream([asyncio.LimitOverrunError("nope", 0)] * 10_000)

    async def collect():
        return [line async for line in brain.iter_lines(stream)]

    assert asyncio.run(asyncio.wait_for(collect(), timeout=5)) == []


def test_ask_reports_an_error_instead_of_dying_silently(monkeypatch):
    # The real failure: ask() is fire-and-forget via create_task, so an
    # unhandled LimitOverrunError just made chat go quiet forever.
    class ExplodingProc:
        returncode = 0
        stdout = FakeStream([RuntimeError("stdout blew up")])
        stderr = FakeStream([])

        async def wait(self):
            return 0

        def kill(self):
            pass

    async def fake_exec(*args, **kwargs):
        return ExplodingProc()

    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_exec)

    hub = FakeHub()
    reply = asyncio.run(brain.ask(hub, "hi"))

    assert reply == ""
    # An error surfaced to the user...
    assert any(brain.ERROR_REPLY in m.get("delta", "") for m in hub.messages)
    # ...and the stream was closed so the UI isn't left hanging.
    assert hub.messages[-1]["done"] is True


def test_ask_streams_deltas_and_closes(monkeypatch):
    class OkProc:
        returncode = 0
        stdout = FakeStream([
            b'{"type":"assistant","message":{"content":[{"type":"text","text":"he"}]}}\n',
            ValueError("Separator is found, but chunk is longer than limit"),
            b'{"type":"assistant","message":{"content":[{"type":"text","text":"llo"}]}}\n',
        ])
        stderr = FakeStream([])

        async def wait(self):
            return 0

        def kill(self):
            pass

    async def fake_exec(*args, **kwargs):
        return OkProc()

    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_exec)

    hub = FakeHub()
    reply = asyncio.run(brain.ask(hub, "hi"))

    assert reply == "hello"
    assert hub.messages[-1]["done"] is True
    assert not any(brain.ERROR_REPLY in m.get("delta", "") for m in hub.messages)


class _Hub:
    def __init__(self): self.msgs = []
    async def broadcast(self, m): self.msgs.append(m)


async def _run_ask(monkeypatch, source):
    """Drive ask() with a fake `claude` that emits one assistant line."""
    import jarvis.services.brain as b

    line = b'{"type":"assistant","message":{"content":[{"type":"text","text":"hello there"}]}}\n'

    class FakeStdout:
        def __init__(self): self.lines = [line, b""]
        async def readline(self): return self.lines.pop(0)

    class FakeStderr:
        async def read(self): return b""

    class FakeProc:
        returncode = 0
        stdout = FakeStdout()
        stderr = FakeStderr()
        async def wait(self): return 0
        def kill(self): pass

    async def fake_exec(*a, **k): return FakeProc()

    monkeypatch.setattr(b.asyncio, "create_subprocess_exec", fake_exec)
    spoken = []
    async def fake_speak(hub, text): spoken.append(text)
    monkeypatch.setattr(b.voice, "speak", fake_speak)

    hub = _Hub()
    reply = await b.ask(hub, "hi", source=source)
    await asyncio.sleep(0)  # let the fire-and-forget speak task run
    return hub, reply, spoken


async def test_voice_turn_writes_nothing_to_chat(monkeypatch):
    hub, reply, spoken = await _run_ask(monkeypatch, "voice")
    assert reply == "hello there"
    assert [m for m in hub.msgs if m.get("type") == "chat"] == [], \
        "a spoken turn must not put any text in the chat panel"
    assert spoken == ["hello there"], "it must still answer out loud"


async def test_typed_turn_still_streams_text(monkeypatch):
    hub, reply, spoken = await _run_ask(monkeypatch, "text")
    chat = [m for m in hub.msgs if m.get("type") == "chat"]
    assert any(m.get("delta") == "hello there" for m in chat)
    assert any(m.get("done") for m in chat)
    assert spoken == ["hello there"]


def test_brain_runs_in_the_vault():
    """The CLI must run inside the vault or it never sees CLAUDE.md."""
    import os
    from jarvis import config
    import jarvis.services.brain as b
    assert os.path.isfile(os.path.join(config.VAULT_PATH, "CLAUDE.md"))
    # Policy changed deliberately: a shell is allowed, but only as a
    # command-by-command allowlist -- never an unrestricted grant.
    assert "Bash(" in b.ALLOWED_TOOLS, "restricted shell access is expected"
    for t in ("Read", "Write", "Edit", "Grep"):
        assert t in b.ALLOWED_TOOLS


def test_session_id_parsed_and_reset():
    import jarvis.services.brain as b
    assert b.parse_session_id('{"type":"system","session_id":"abc-123"}') == "abc-123"
    assert b.parse_session_id('{"type":"system"}') is None
    assert b.parse_session_id("not json") is None
    b._session_id = "abc"
    b.reset_session()
    assert b._session_id is None


def test_destructive_shell_commands_are_not_allowlisted():
    """Headless mode can't prompt, so the allowlist IS the enforcement.
    A misheard phrase must not be able to reach a destructive command."""
    import jarvis.services.brain as b
    for danger in ("Bash(rm", "Bash(del", "Bash(format", "Bash(git push",
                   "Bash(shutdown", "Bash(curl", "Bash(*)"):
        assert danger not in b.ALLOWED_TOOLS, danger
    # a bare unrestricted Bash grant would defeat the whole allowlist
    assert ",Bash," not in "," + b.ALLOWED_TOOLS + ","


def test_safe_shell_commands_are_allowlisted():
    import jarvis.services.brain as b
    for ok in ("Bash(pytest:*)", "Bash(git status:*)", "Bash(git diff:*)"):
        assert ok in b.ALLOWED_TOOLS, ok


def test_extra_dirs_cover_home_and_self_but_not_drive_root():
    from jarvis import config
    joined = " ".join(config.EXTRA_DIRS)
    assert "jarvis-hud" in joined, "must be able to edit its own code"
    assert r"C:\Users\Mackenzie" in joined, "must reach Mackenzie's files"
    assert "C:\\\\" not in [d.strip() for d in config.EXTRA_DIRS]
    assert "C:\\" not in [d.strip() for d in config.EXTRA_DIRS], \
        "drive root would expose Windows system files"
