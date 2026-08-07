import json

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
