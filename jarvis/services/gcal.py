import asyncio
import datetime as dt

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials

from jarvis import config

SCOPES = ["https://www.googleapis.com/auth/calendar.readonly"]
TOKEN_PATH = config.ROOT / "token.json"
CREDENTIALS_PATH = config.ROOT / "credentials.json"


def _fmt_time(iso: str) -> str:
    """dateTime -> 12-hour clock, no leading zero, e.g. '9:00 AM' / '12:15 AM'."""
    # fromisoformat handles the offset (e.g. -04:00) Google always includes;
    # we only need the local wall-clock hour/minute it already represents.
    d = dt.datetime.fromisoformat(iso)
    hour12 = d.hour % 12 or 12
    return f"{hour12}:{d.minute:02d} {'AM' if d.hour < 12 else 'PM'}"


def format_events(raw: list[dict]) -> dict:
    """Pure transform: Google Calendar API events -> HUD calendar payload.

    All-day events (start.date, no start.dateTime) sort before timed events
    and get a fixed "all day" label instead of a made-up clock time.
    """
    items = []
    for ev in raw:
        start = ev.get("start", {})
        title = ev.get("summary") or "(no title)"
        date_time = start.get("dateTime")
        if date_time:
            items.append((0, date_time, _fmt_time(date_time), title))
        else:
            # No dateTime to sort by -- use the date so all-day events still
            # sort relative to each other, but keep them ahead of timed ones.
            items.append((-1, start.get("date", ""), "all day", title))

    items.sort(key=lambda t: (t[0], t[1]))
    return {"type": "calendar", "events": [{"time": t[2], "title": t[3]} for t in items]}


def _load_credentials() -> Credentials | None:
    """Load token.json, refreshing an expired token in place. Never logs the
    token itself -- only the fact that it did/didn't work."""
    if not TOKEN_PATH.exists():
        return None
    creds = Credentials.from_authorized_user_file(str(TOKEN_PATH), SCOPES)
    if creds.valid:
        return creds
    if creds.expired and creds.refresh_token:
        creds.refresh(Request())
        TOKEN_PATH.write_text(creds.to_json())
        return creds
    return None


def _fetch_today_events(creds: Credentials) -> list[dict]:
    """Blocking Google API call -- run this via asyncio.to_thread."""
    # Imported lazily so a missing/broken googleapiclient install can't break
    # module import for callers that only need format_events (e.g. tests).
    from googleapiclient.discovery import build

    now = dt.datetime.now().astimezone()
    start_of_day = now.replace(hour=0, minute=0, second=0, microsecond=0)
    end_of_day = start_of_day + dt.timedelta(days=1)

    service = build("calendar", "v3", credentials=creds)
    result = service.events().list(
        calendarId=config.GOOGLE_CALENDAR_ID,
        timeMin=start_of_day.isoformat(),
        timeMax=end_of_day.isoformat(),
        singleEvents=True,
        orderBy="startTime",
    ).execute()
    return result.get("items", [])


async def run(hub, interval: float = 300.0):
    # No consent yet -- tell him how to fix it and stop, same shape as
    # vault.run's "no API key configured" bail-out. Looping here would just
    # spam offline broadcasts every cycle for a condition that never changes
    # without him running scripts/gcal_auth.py.
    if not TOKEN_PATH.exists():
        await hub.broadcast({
            "type": "status", "service": "calendar", "state": "offline",
            "detail": "not authorized -- run scripts/gcal_auth.py",
        })
        return

    while True:
        try:
            creds = await asyncio.to_thread(_load_credentials)
            if creds is None:
                raise RuntimeError("token.json is invalid or revoked -- re-run scripts/gcal_auth.py")
            raw = await asyncio.to_thread(_fetch_today_events, creds)
            await hub.broadcast(format_events(raw))
        except Exception as e:
            await hub.broadcast({"type": "status", "service": "calendar", "state": "offline", "detail": str(e)})

        await asyncio.sleep(interval)
