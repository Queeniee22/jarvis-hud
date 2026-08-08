from jarvis.services.gcal import format_events


def test_format_events_sorts_and_uses_12_hour_time():
    raw = [
        {"start": {"dateTime": "2026-08-06T14:00:00-04:00"}, "summary": "Interview"},
        {"start": {"dateTime": "2026-08-06T09:00:00-04:00"}, "summary": "Stand-up"},
    ]
    assert format_events(raw) == {"type": "calendar", "events": [
        {"time": "9:00 AM", "title": "Stand-up"},
        {"time": "2:00 PM", "title": "Interview"},
    ]}


def test_format_events_handles_all_day_and_missing_title():
    raw = [
        {"start": {"date": "2026-08-06"}},
        {"start": {"dateTime": "2026-08-06T12:30:00-04:00"}, "summary": "Lunch"},
    ]
    out = format_events(raw)
    titles = [e["title"] for e in out["events"]]
    assert "(no title)" in titles
    assert {"time": "12:30 PM", "title": "Lunch"} in out["events"]
    # an all-day event must be labelled, not rendered as a bogus clock time
    allday = [e for e in out["events"] if e["title"] == "(no title)"][0]
    assert allday["time"].lower() in ("all day", "all-day")


def test_format_events_empty():
    assert format_events([]) == {"type": "calendar", "events": []}


def test_midnight_and_noon_format_correctly():
    raw = [
        {"start": {"dateTime": "2026-08-06T00:15:00-04:00"}, "summary": "Late"},
        {"start": {"dateTime": "2026-08-06T12:00:00-04:00"}, "summary": "Noon"},
    ]
    events = format_events(raw)["events"]
    assert {"time": "12:15 AM", "title": "Late"} in events
    assert {"time": "12:00 PM", "title": "Noon"} in events


async def test_run_broadcasts_offline_when_no_token(monkeypatch, tmp_path):
    from jarvis.services import gcal

    # No token.json on disk -- the not-authorized path must broadcast and
    # return immediately rather than looping, so this test can't hang.
    monkeypatch.setattr(gcal, "TOKEN_PATH", tmp_path / "token.json")

    broadcasts = []

    class FakeHub:
        async def broadcast(self, message):
            broadcasts.append(message)

    await gcal.run(FakeHub())

    assert len(broadcasts) == 1
    msg = broadcasts[0]
    assert msg["type"] == "status"
    assert msg["service"] == "calendar"
    assert msg["state"] == "offline"
    assert "detail" in msg
