"""Session-start: read the vault before saying anything.

The vault's CLAUDE.md defines a session-start protocol -- read Standing
Instructions and About Mackenzie, then today's daily note. This runs it once
at startup so Jarvis wakes up already knowing who Mackenzie is and what today
looks like, and greets him out loud with it.
"""
import asyncio
import datetime as dt
import logging

from jarvis import config
from jarvis.services import brain, voice

log = logging.getLogger(__name__)

# Deliberately phrased as a normal turn so the CLI follows the vault's
# CLAUDE.md protocol itself rather than us reimplementing it here.
BOOT_PROMPT = (
    "Session start. Follow your CLAUDE.md session-start protocol: read "
    "'01 Preferences/Standing Instructions.md' and "
    "'01 Preferences/About Mackenzie.md', then today's note in '05 Daily/' "
    "if it exists. Then greet Mackenzie out loud in ONE short sentence -- "
    "mention at most one concrete thing you found that's relevant to today. "
    "No lists, no markdown. If there's nothing notable, just say hello."
)


def today_note_path() -> str:
    return f"05 Daily/{dt.date.today().isoformat()}.md"


async def run(hub, delay: float = 1.0):
    """Read the vault, then greet. Never fatal -- a failed boot just means
    no greeting, and the HUD carries on."""
    await asyncio.sleep(delay)  # let the socket and panels come up first
    try:
        await hub.broadcast({
            "type": "status", "service": "boot", "state": "reading",
            "detail": "reading vault",
        })
        # source="voice" so the greeting is spoken and leaves the chat panel
        # clean, matching how spoken turns behave everywhere else.
        # Not a "heard" message: that caption means "what the mic picked up",
        # and putting Jarvis's own greeting there reads like a mishearing.
        greeting = await brain.ask(hub, BOOT_PROMPT, source="voice")
        await hub.broadcast({
            "type": "status", "service": "boot", "state": "ready",
            "detail": "vault loaded",
        })
        log.info("boot: vault read, greeted")
    except Exception as e:
        log.warning("boot: session-start failed: %s", e)
        await hub.broadcast({
            "type": "status", "service": "boot", "state": "error",
            "detail": str(e),
        })
