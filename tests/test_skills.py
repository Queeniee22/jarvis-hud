import asyncio
import datetime as dt

import pytest

from jarvis.services import skills

REAL_SHAPED_NOTE = """---
created: 2026-08-08
updated: 2026-08-08
tags: [skill]
skill: true
name: Morning Brief
icon: "*"
schedule: daily 07:00
output: 05 Daily/
---

# Morning Brief

## Prompt

Read the Run log at the bottom of this note first, and apply anything learned there.

Then put together the brief.

## Run log

_Jarvis appends what it learned after each run. Read this before running._
"""

NOT_A_SKILL_NOTE = """---
created: 2026-08-08
updated: 2026-08-08
tags: [skills/index]
---

# Skills

Just an index note, not a runnable skill.
"""


def test_parse_skill_on_a_real_shaped_note():
    skill = skills.parse_skill("06 Skills/Morning Brief.md", REAL_SHAPED_NOTE)
    assert skill is not None
    assert skill["id"] == "06 Skills/Morning Brief.md"
    assert skill["name"] == "Morning Brief"
    assert skill["icon"] == "*"
    assert skill["schedule"] == "daily 07:00"
    assert skill["output"] == "05 Daily/"
    assert "Then put together the brief." in skill["prompt"]
    assert "Read the Run log" in skill["prompt"]
    assert "## Prompt" not in skill["prompt"]
    assert "Jarvis appends what it learned" in skill["runlog"]


def test_parse_skill_without_skill_true_returns_none():
    assert skills.parse_skill("06 Skills/README.md", NOT_A_SKILL_NOTE) is None


def test_parse_skill_falls_back_to_filename_for_name():
    note = """---
skill: true
---

## Prompt

do the thing

## Run log
"""
    skill = skills.parse_skill("06 Skills/Vault Cleanup.md", note)
    assert skill["name"] == "Vault Cleanup"


def test_parse_skill_handles_missing_frontmatter():
    assert skills.parse_skill("06 Skills/X.md", "# just a note\nno frontmatter here") is None


def test_parse_skill_handles_no_prompt_or_runlog_sections():
    note = "---\nskill: true\nname: Bare\n---\n\n# Bare\n\nnothing else here"
    skill = skills.parse_skill("06 Skills/Bare.md", note)
    assert skill["prompt"] == ""
    assert skill["runlog"] == ""


@pytest.mark.parametrize("text,expected", [
    ("hourly", {"kind": "hourly"}),
    ("daily 07:00", {"kind": "daily", "hour": 7, "minute": 0}),
    ("daily 23:59", {"kind": "daily", "hour": 23, "minute": 59}),
    ("weekly sun 18:00", {"kind": "weekly", "dow": 6, "hour": 18, "minute": 0}),
    ("WEEKLY Mon 09:30", {"kind": "weekly", "dow": 0, "hour": 9, "minute": 30}),
])
def test_parse_schedule_accepted_forms(text, expected):
    assert skills.parse_schedule(text) == expected


@pytest.mark.parametrize("text", [
    "", None, "monthly", "daily", "daily 7am", "daily 25:00", "daily 07:70",
    "weekly 18:00", "weekly notaday 18:00", "every day at 7", "hourly 07:00",
])
def test_parse_schedule_rejects_garbage(text):
    assert skills.parse_schedule(text) is None


def test_due_daily_does_not_fire_retroactively_on_startup():
    """A schedule that already passed today must not fire just because the
    service happens to check for the first time after it."""
    schedule = skills.parse_schedule("daily 07:00")
    now = dt.datetime(2026, 8, 8, 9, 0)  # 7am has already passed
    assert skills.due(schedule, now, last_run=None) is False


def test_due_daily_fires_exactly_when_the_time_arrives():
    schedule = skills.parse_schedule("daily 07:00")
    now = dt.datetime(2026, 8, 8, 7, 0)
    assert skills.due(schedule, now, last_run=None) is True


def test_due_daily_does_not_double_fire_in_the_same_slot():
    schedule = skills.parse_schedule("daily 07:00")
    first = dt.datetime(2026, 8, 8, 7, 0)
    assert skills.due(schedule, first, last_run=None) is True
    later_same_minute = dt.datetime(2026, 8, 8, 7, 0, 45)
    assert skills.due(schedule, later_same_minute, last_run=first) is False
    later_same_day = dt.datetime(2026, 8, 8, 20, 0)
    assert skills.due(schedule, later_same_day, last_run=first) is False


def test_due_daily_fires_again_the_next_day():
    schedule = skills.parse_schedule("daily 07:00")
    yesterday = dt.datetime(2026, 8, 7, 7, 0)
    today = dt.datetime(2026, 8, 8, 7, 0)
    assert skills.due(schedule, today, last_run=yesterday) is True


def test_due_hourly_fires_on_the_hour_and_not_twice():
    schedule = skills.parse_schedule("hourly")
    on_the_hour = dt.datetime(2026, 8, 8, 14, 0)
    assert skills.due(schedule, on_the_hour, last_run=None) is True
    assert skills.due(schedule, dt.datetime(2026, 8, 8, 14, 30), last_run=on_the_hour) is False
    assert skills.due(schedule, on_the_hour, last_run=on_the_hour) is False
    assert skills.due(schedule, dt.datetime(2026, 8, 8, 15, 0), last_run=on_the_hour) is True


def test_due_weekly_only_fires_on_the_right_weekday():
    schedule = skills.parse_schedule("weekly sun 18:00")
    sunday = dt.datetime(2026, 8, 9, 18, 0)  # a Sunday
    monday = dt.datetime(2026, 8, 10, 18, 0)  # not a Sunday
    assert sunday.weekday() == 6
    assert skills.due(schedule, sunday, last_run=None) is True
    assert skills.due(schedule, monday, last_run=None) is False


def test_due_with_no_schedule_never_fires():
    assert skills.due(None, dt.datetime.now(), last_run=None) is False


def test_list_skills_skips_readme_and_non_skill_notes(monkeypatch):
    files = ["06 Skills/README.md", "06 Skills/Morning Brief.md", "06 Skills/Vault Cleanup.md"]
    contents = {
        "06 Skills/README.md": NOT_A_SKILL_NOTE,
        "06 Skills/Morning Brief.md": REAL_SHAPED_NOTE,
        "06 Skills/Vault Cleanup.md": (
            "---\nskill: true\nname: Vault Cleanup\nicon: \"~\"\n---\n\n"
            "## Prompt\n\ntidy up\n\n## Run log\n"
        ),
    }
    monkeypatch.setattr(skills.vault, "list_files", lambda dir_path="": files)
    monkeypatch.setattr(skills.vault, "read_note", lambda path: contents[path])

    result = skills.list_skills()

    names = [s["name"] for s in result]
    assert names == ["Morning Brief", "Vault Cleanup"], "sorted by name, README excluded"


def test_list_skills_skips_a_note_it_cannot_read(monkeypatch):
    """A single bad note must not take down the whole list."""
    files = ["06 Skills/Morning Brief.md", "06 Skills/Broken.md"]

    def fake_read(path):
        if path.endswith("Broken.md"):
            raise ConnectionError("vault down for this note")
        return REAL_SHAPED_NOTE

    monkeypatch.setattr(skills.vault, "list_files", lambda dir_path="": files)
    monkeypatch.setattr(skills.vault, "read_note", fake_read)

    result = skills.list_skills()
    assert [s["name"] for s in result] == ["Morning Brief"]


def test_build_prompt_includes_runlog_instruction_and_path():
    skill = skills.parse_skill("06 Skills/Morning Brief.md", REAL_SHAPED_NOTE)
    prompt = skills.build_prompt(skill)
    assert "06 Skills/Morning Brief.md" in prompt
    assert "Run log" in prompt
    assert "Then put together the brief." in prompt


class FakeHub:
    def __init__(self):
        self.messages = []

    async def broadcast(self, message):
        self.messages.append(message)


def _one_skill():
    return [skills.parse_skill("06 Skills/Morning Brief.md", REAL_SHAPED_NOTE)]


async def test_run_skill_broadcasts_running_then_done(monkeypatch):
    monkeypatch.setattr(skills, "list_skills", _one_skill)

    async def fake_ask(hub, text, source="text"):
        assert source == "voice"
        return "done"

    monkeypatch.setattr(skills.brain, "ask", fake_ask)
    skills._last_run.clear()

    hub = FakeHub()
    await skills.run_skill(hub, "06 Skills/Morning Brief.md")

    states = [m["state"] for m in hub.messages if m["type"] == "skill"]
    assert states == ["running", "done"]
    assert "06 Skills/Morning Brief.md" in skills._last_run


async def test_run_skill_broadcasts_running_then_error_without_raising(monkeypatch):
    monkeypatch.setattr(skills, "list_skills", _one_skill)

    async def failing_ask(hub, text, source="text"):
        raise RuntimeError("claude blew up")

    monkeypatch.setattr(skills.brain, "ask", failing_ask)
    skills._last_run.clear()

    hub = FakeHub()
    await skills.run_skill(hub, "06 Skills/Morning Brief.md")  # must not raise

    states = [m["state"] for m in hub.messages if m["type"] == "skill"]
    assert states == ["running", "error"]
    error_msg = [m for m in hub.messages if m["type"] == "skill" and m["state"] == "error"][0]
    assert "claude blew up" in error_msg["detail"]
    assert "06 Skills/Morning Brief.md" in skills._last_run


async def test_run_skill_unknown_id_reports_error(monkeypatch):
    monkeypatch.setattr(skills, "list_skills", lambda: [])
    hub = FakeHub()
    await skills.run_skill(hub, "nope")
    states = [m["state"] for m in hub.messages if m["type"] == "skill"]
    assert states == ["error"]


async def test_concurrent_run_skill_calls_do_not_overlap(monkeypatch):
    """The second call while one is in flight must report busy immediately,
    not queue silently behind the lock."""
    monkeypatch.setattr(skills, "list_skills", _one_skill)
    skills._last_run.clear()

    started = asyncio.Event()
    release = asyncio.Event()

    async def slow_ask(hub, text, source="text"):
        started.set()
        await release.wait()
        return "ok"

    monkeypatch.setattr(skills.brain, "ask", slow_ask)

    hub = FakeHub()
    first = asyncio.create_task(skills.run_skill(hub, "06 Skills/Morning Brief.md"))
    await started.wait()

    hub2 = FakeHub()
    await skills.run_skill(hub2, "06 Skills/Morning Brief.md")
    assert [m["state"] for m in hub2.messages] == ["busy"]

    release.set()
    await first

    states = [m["state"] for m in hub.messages if m["type"] == "skill"]
    assert states == ["running", "done"]


async def test_run_broadcasts_skills_list_and_status_online(monkeypatch):
    monkeypatch.setattr(skills, "list_skills", _one_skill)
    hub = FakeHub()

    task = asyncio.create_task(skills.run(hub, interval=3600))
    for _ in range(50):
        await asyncio.sleep(0.01)
        if any(m.get("type") == "skills" for m in hub.messages):
            break
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass

    skills_msgs = [m for m in hub.messages if m["type"] == "skills"]
    assert skills_msgs, "no skills list broadcast"
    assert skills_msgs[0]["skills"][0]["name"] == "Morning Brief"
    statuses = [m for m in hub.messages if m["type"] == "status" and m.get("service") == "skills"]
    assert statuses and statuses[-1]["state"] == "online"


async def test_run_does_not_stop_when_a_scheduled_skill_run_fails(monkeypatch):
    """A skill whose schedule is due and whose brain call fails must not take
    down the scanning loop -- run_skill already isolates its own errors."""
    due_skill = skills.parse_skill(
        "06 Skills/Hourly Thing.md",
        "---\nskill: true\nname: Hourly Thing\nschedule: hourly\n---\n\n## Prompt\n\ndo it\n\n## Run log\n",
    )
    monkeypatch.setattr(skills, "list_skills", lambda: [due_skill])
    # Force the schedule check to fire every cycle rather than depending on
    # the real wall clock landing exactly on the hour during the test run.
    monkeypatch.setattr(skills, "due", lambda schedule, now, last_run: True)

    async def failing_ask(hub, text, source="text"):
        raise RuntimeError("boom")

    monkeypatch.setattr(skills.brain, "ask", failing_ask)
    skills._last_run.clear()

    hub = FakeHub()
    task = asyncio.create_task(skills.run(hub, interval=0.02))
    await asyncio.sleep(0.15)
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass

    statuses = [m for m in hub.messages if m["type"] == "status" and m.get("service") == "skills"]
    assert statuses and statuses[-1]["state"] == "online", "the scan loop must survive a failing skill"
