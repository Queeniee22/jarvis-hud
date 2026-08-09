import asyncio
import datetime as dt
import logging

from jarvis.services import brain, vault

log = logging.getLogger(__name__)

SKILLS_DIR = "06 Skills/"
README_NAME = "README.md"

_DOWS = {"mon": 0, "tue": 1, "wed": 2, "thu": 3, "fri": 4, "sat": 5, "sun": 6}


def _clean_value(v: str) -> str:
    """'"Morning Brief"' -> 'Morning Brief'. Frontmatter here is hand-written,
    not a real YAML parser, so quoting is optional and this just strips it
    when present."""
    v = v.strip()
    if len(v) >= 2 and v[0] == v[-1] and v[0] in "\"'":
        v = v[1:-1]
    return v


def _section(body: str, heading: str) -> str:
    """Text under a '## Heading' line, up to the next '##' heading (or EOF).
    Returns '' if the heading is not present."""
    lines = body.splitlines()
    start = None
    for i, line in enumerate(lines):
        if line.strip() == heading:
            start = i
            break
    if start is None:
        return ""
    collected = []
    for line in lines[start + 1:]:
        if line.strip().startswith("##"):
            break
        collected.append(line)
    return "\n".join(collected).strip()


def parse_skill(path: str, content: str) -> dict | None:
    """Parse one skill note's frontmatter + sections. Pure, no I/O.

    Frontmatter is simple `key: value` lines between `---` fences -- the
    vault deliberately has no yaml dependency, so this is not a real YAML
    parser, just enough of one for the shape README.md documents.
    """
    lines = content.splitlines()
    if not lines or lines[0].strip() != "---":
        return None
    meta = {}
    i = 1
    while i < len(lines) and lines[i].strip() != "---":
        line = lines[i]
        if ":" in line:
            key, _, value = line.partition(":")
            meta[key.strip()] = _clean_value(value)
        i += 1
    if i >= len(lines):
        return None  # unterminated frontmatter -- not a real note
    if meta.get("skill", "").lower() != "true":
        return None

    body = "\n".join(lines[i + 1:])
    name = meta.get("name") or path.rsplit("/", 1)[-1].removesuffix(".md")

    return {
        "id": path,
        "name": name,
        "icon": meta.get("icon") or None,
        "schedule": meta.get("schedule") or None,
        "output": meta.get("output") or None,
        "prompt": _section(body, "## Prompt"),
        "runlog": _section(body, "## Run log"),
    }


def list_skills() -> list[dict]:
    """Every skill note in 06 Skills/, sorted by name. Skips the README and
    any note without `skill: true`."""
    files = vault.list_files(SKILLS_DIR)
    skills = []
    for f in files:
        if f.rsplit("/", 1)[-1] == README_NAME:
            continue
        try:
            content = vault.read_note(f)
        except Exception:
            log.warning("skills: could not read %s", f)
            continue
        skill = parse_skill(f, content)
        if skill:
            skills.append(skill)
    skills.sort(key=lambda s: s["name"])
    return skills


def _parse_hhmm(s: str):
    if ":" not in s:
        return None
    h, _, m = s.partition(":")
    try:
        h, m = int(h), int(m)
    except ValueError:
        return None
    if not (0 <= h < 24 and 0 <= m < 60):
        return None
    return h, m


def parse_schedule(text: str) -> dict | None:
    """Accept exactly 'hourly', 'daily HH:MM', 'weekly <dow> HH:MM'
    (case-insensitive). Anything else -> None. Pure -- callers log the
    warning, this never raises."""
    if not text:
        return None
    parts = text.strip().lower().split()
    if not parts:
        return None
    kind = parts[0]
    if kind == "hourly" and len(parts) == 1:
        return {"kind": "hourly"}
    if kind == "daily" and len(parts) == 2:
        hm = _parse_hhmm(parts[1])
        return {"kind": "daily", "hour": hm[0], "minute": hm[1]} if hm else None
    if kind == "weekly" and len(parts) == 3:
        dow = _DOWS.get(parts[1])
        hm = _parse_hhmm(parts[2])
        if dow is None or hm is None:
            return None
        return {"kind": "weekly", "dow": dow, "hour": hm[0], "minute": hm[1]}
    return None


def due(schedule: dict | None, now: dt.datetime, last_run: dt.datetime | None) -> bool:
    """Whether `schedule` should fire at `now`, given it last fired at
    `last_run` (or never).

    Fires only inside the exact scheduled minute -- not "any time after" --
    which is what keeps a time that already passed today from firing
    retroactively the moment the service starts back up (the service loop
    checks every 30s, so any given minute gets checked at least once, and
    this window doesn't need to be widened for that). Dedup against
    `last_run` then stops a second check landing in the same minute -- or a
    second cycle later the same day/hour -- from firing again.
    """
    if not schedule:
        return False
    kind = schedule["kind"]
    if kind == "hourly":
        if now.minute != 0:
            return False
        slot = (now.year, now.month, now.day, now.hour)
        if last_run is not None and (last_run.year, last_run.month, last_run.day, last_run.hour) == slot:
            return False
        return True
    if kind in ("daily", "weekly"):
        if now.hour != schedule["hour"] or now.minute != schedule["minute"]:
            return False
        if kind == "weekly" and now.weekday() != schedule["dow"]:
            return False
        if last_run is not None and last_run.date() == now.date():
            return False
        return True
    return False


def build_prompt(skill: dict) -> str:
    """The text handed to brain.ask for a skill run."""
    path = skill["id"]
    return (
        f"Read the '## Run log' section at the bottom of the skill note "
        f"'{path}' first, and apply anything learned there. Then do exactly "
        f"what its '## Prompt' section below says:\n\n"
        f"---\n{skill['prompt']}\n---\n\n"
        f"When you are done, append a short dated entry (2-4 lines) to the "
        f"'## Run log' section of '{path}' recording what you did, what was "
        f"awkward, and what to do differently next time. Do not rewrite the "
        f"Prompt section itself."
    )


# Two skills must never run at once -- a scheduled fire colliding with a
# button press, or two clicks in a row, would otherwise step on the same
# `claude` subprocess / session. Serialised behind this lock rather than
# queued: an indefinite queue could stack up minutes of runs behind one slow
# skill, so a collision is reported as "busy" instead.
_lock = asyncio.Lock()
_last_run: dict[str, dt.datetime] = {}


async def run_skill(hub, skill_id: str, extra: str = "") -> None:
    if _lock.locked():
        await hub.broadcast({"type": "skill", "state": "busy", "id": skill_id})
        return
    async with _lock:
        try:
            skills = await asyncio.to_thread(list_skills)
        except Exception as e:
            await hub.broadcast({"type": "skill", "state": "error", "id": skill_id, "detail": str(e)})
            return
        skill = next((s for s in skills if s["id"] == skill_id), None)
        if skill is None:
            await hub.broadcast({"type": "skill", "state": "error", "id": skill_id, "detail": "unknown skill"})
            return
        await hub.broadcast({"type": "skill", "state": "running", "id": skill_id, "name": skill["name"]})
        try:
            # source="voice" so the result is both spoken and written to
            # chat -- a skill run is a real turn, not a silent background job.
            await brain.ask(hub, build_prompt(skill) + extra, source="voice")
            await hub.broadcast({"type": "skill", "state": "done", "id": skill_id, "name": skill["name"]})
        except Exception as e:
            log.exception("skills: run_skill failed for %s", skill_id)
            await hub.broadcast({
                "type": "skill", "state": "error", "id": skill_id,
                "name": skill["name"], "detail": str(e),
            })
        finally:
            # Recorded on success, error, or lookup failure alike -- a skill
            # that keeps failing at 7am should not retry every 30s until it
            # works, it should wait for tomorrow like a healthy run would.
            _last_run[skill_id] = dt.datetime.now()


async def run(hub, interval: float = 30.0):
    """Refresh the skill list and fire anything due, once per cycle.

    Re-listing every cycle costs one vault directory walk plus one GET per
    skill note. That's fine for a handful of small notes in 06 Skills/, but
    it would need caching (or a longer interval) if that folder ever grew
    large enough for the cost to matter.
    """
    online: bool | None = None
    last_summary: list | None = None

    while True:
        try:
            skills = await asyncio.to_thread(list_skills)
            summary = [
                {"id": s["id"], "name": s["name"], "icon": s["icon"], "schedule": s["schedule"]}
                for s in skills
            ]
            if summary != last_summary:
                await hub.broadcast({"type": "skills", "skills": summary})
                last_summary = summary

            now = dt.datetime.now()
            for s in skills:
                if not s["schedule"]:
                    continue
                schedule = parse_schedule(s["schedule"])
                if schedule is None:
                    log.warning("skills: could not parse schedule %r for %s", s["schedule"], s["id"])
                    continue
                if due(schedule, now, _last_run.get(s["id"])):
                    # Fire-and-forget: run_skill's own lock is what actually
                    # serialises execution, so this loop must not block on it
                    # (a slow skill would otherwise stall the whole scan).
                    asyncio.create_task(run_skill(hub, s["id"]))

            if online is not True:
                await hub.broadcast({"type": "status", "service": "skills", "state": "online"})
                online = True
        except Exception as e:
            # One failing skill run must never stop the loop -- run_skill
            # already isolates its own exceptions, so anything reaching here
            # is the scan itself (a dead vault, a bad listing).
            if online is not False:
                await hub.broadcast({"type": "status", "service": "skills", "state": "offline", "detail": str(e)})
                online = False

        await asyncio.sleep(interval)
