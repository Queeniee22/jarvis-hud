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
