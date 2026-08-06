from jarvis.services.brain import parse_stream_line


def test_parse_assistant_text_delta():
    line = '{"type":"assistant","message":{"content":[{"type":"text","text":"hi"}]}}'
    assert parse_stream_line(line) == "hi"


def test_parse_non_text_returns_none():
    assert parse_stream_line('{"type":"system","subtype":"init"}') is None


def test_parse_garbage_returns_none():
    assert parse_stream_line("not json") is None
