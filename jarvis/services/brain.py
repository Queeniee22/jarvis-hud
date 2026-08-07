import asyncio
import json
import logging
import shutil

from jarvis import config
from jarvis.services import voice

log = logging.getLogger(__name__)

SYSTEM_PROMPT = (
    "You are Jarvis, Mackenzie's cute, terse personal assistant. "
    "Warm, direct, a little playful. Short answers; reasoning on request. "
    "You are speaking aloud, so keep replies to a couple of sentences and "
    "avoid markdown, bullet lists, code blocks, or anything that only makes "
    "sense on screen. "
    "Your working directory is Mackenzie's Obsidian vault and its CLAUDE.md "
    "is your memory protocol -- follow it. Search the vault before saying you "
    "don't know. When you learn something durable, write it to the right note: "
    "corrections Mackenzie gives you go in the 'Observed preferences' section "
    "of '01 Preferences/Working Style.md', problems and their real fixes go in "
    "'02 Programming/Debug Log.md', and anything time-bound gets appended to "
    "today's note in '05 Daily/'. Prefer updating an existing note over "
    "creating a near-duplicate."
)

# File tools only. A voice assistant acting on a misheard phrase must not be
# able to run shell commands, so Bash is deliberately withheld.
ALLOWED_TOOLS = "Read,Write,Edit,Glob,Grep"

# The CLI spawns fresh per turn, so without resuming a session every turn is
# amnesiac -- it could not remember the previous sentence, let alone learn.
_session_id = None


def reset_session():
    """Forget the conversation, so the next turn starts a fresh session."""
    global _session_id
    _session_id = None


def parse_session_id(line: str):
    """Pull the session id out of a stream-json line, if it carries one."""
    try:
        obj = json.loads(line)
    except Exception:
        return None
    sid = obj.get("session_id")
    return sid or None

# asyncio's default StreamReader limit is 64KB, which a single stream-json
# line clears easily. Raise it, but keep it bounded — an unbounded reader
# lets a runaway subprocess eat all our memory.
STREAM_LIMIT = 8 * 1024 * 1024

ERROR_REPLY = "sorry — my brain dropped that one. try again?"

# A stream that reports errors without consuming anything would spin here
# forever, and the error path has no await, so it would wedge the event
# loop rather than merely burning a task. Real StreamReaders always drain;
# this is just a backstop.
_MAX_CONSECUTIVE_READ_ERRORS = 10


def parse_stream_line(line: str):
    try:
        obj = json.loads(line)
    except Exception:
        return None
    if obj.get("type") != "assistant":
        return None
    parts = obj.get("message", {}).get("content", [])
    text = "".join(p.get("text", "") for p in parts if p.get("type") == "text")
    return text or None


async def iter_lines(stream):
    """Yield decoded lines from `stream`, skipping any that blow the limit.

    Iterating a StreamReader with `async for` lets readline()'s ValueError
    (raised on LimitOverrunError) escape and kill the task. readline() has
    already drained the oversized data by the time it raises, so the right
    move is to drop that one line and keep reading.
    """
    errors = 0
    while True:
        try:
            raw = await stream.readline()
        except (ValueError, asyncio.LimitOverrunError) as exc:
            errors += 1
            log.warning("brain: dropping unreadable stdout line (%s)", exc)
            if errors >= _MAX_CONSECUTIVE_READ_ERRORS:
                log.error("brain: giving up on stdout after %d read errors", errors)
                return
            continue
        errors = 0
        if not raw:
            return
        yield raw.decode("utf-8", "ignore").strip()


async def ask(hub, text: str, source: str = "text"):
    """Ask Claude and stream the reply.

    `source` is the modality the request arrived on, and it decides how the
    answer comes back. A spoken question gets a spoken answer only: nothing
    is written to the chat panel, so talking to Jarvis leaves no transcript
    clutter. A typed question still streams text (and is also spoken).
    """
    voice_only = source == "voice"

    async def emit(message):
        """Chat-panel output, suppressed entirely for spoken turns."""
        if not voice_only:
            await hub.broadcast(message)

    if voice_only:
        # Say something immediately. The CLI turn below takes ~5s of mostly
        # fixed startup, so without a filler you'd get several seconds of
        # silence and no sign it heard you.
        asyncio.create_task(voice.speak_ack(hub))

    reply = ""
    proc = None
    claude_path = shutil.which("claude") or "claude"
    try:
        global _session_id
        args = [claude_path, "-p", text,
                "--append-system-prompt", SYSTEM_PROMPT,
                "--permission-mode", "acceptEdits",
                "--allowedTools", ALLOWED_TOOLS,
                "--output-format", "stream-json", "--verbose"]
        if _session_id:
            args += ["--resume", _session_id]
        proc = await asyncio.create_subprocess_exec(
            *args,
            # Run inside the vault so the CLI loads its CLAUDE.md memory
            # protocol and can read/write notes directly.
            cwd=config.VAULT_PATH,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
            limit=STREAM_LIMIT,
        )
        # Drain stderr concurrently: nobody reading it means a chatty
        # subprocess fills the pipe buffer and blocks forever mid-reply.
        stderr_task = asyncio.create_task(proc.stderr.read())

        async for line in iter_lines(proc.stdout):
            sid = parse_session_id(line)
            if sid:
                _session_id = sid
            delta = parse_stream_line(line)
            if delta:
                reply += delta
                await emit({"type": "chat", "role": "jarvis", "delta": delta, "done": False})

        await proc.wait()
        stderr = (await stderr_task).decode("utf-8", "ignore").strip()
        if proc.returncode:
            log.error("brain: claude exited %s: %s", proc.returncode, stderr[-2000:])
            if not reply:
                # A resumed session that the CLI won't accept would fail every
                # turn from here on. Drop it so the next turn starts clean.
                if _session_id:
                    log.warning("brain: dropping session %s after failure", _session_id)
                    _session_id = None
                await emit(
                    {"type": "chat", "role": "jarvis", "delta": ERROR_REPLY, "done": False}
                )
                if voice_only:
                    await hub.broadcast({
                        "type": "status", "service": "brain", "state": "error",
                        "detail": f"claude exited {proc.returncode}",
                    })
    except asyncio.CancelledError:
        raise
    except Exception:
        # ask() is fired off with create_task, so an escaping exception
        # would just leave chat silent. Say something instead.
        log.exception("brain: ask failed")
        if proc is not None and proc.returncode is None:
            proc.kill()
        await emit(
            {"type": "chat", "role": "jarvis", "delta": ERROR_REPLY, "done": False}
        )
        if voice_only:
            # Nothing was written to chat, so without this a failed spoken
            # turn would be completely silent and invisible.
            await hub.broadcast({
                "type": "status", "service": "brain", "state": "error",
                "detail": "ask failed",
            })
    finally:
        await emit({"type": "chat", "role": "jarvis", "delta": "", "done": True})
        if reply:
            asyncio.create_task(voice.speak(hub, reply))
        elif voice_only:
            # A spoken turn writes nothing to the panel, so a failure with no
            # reply would be pure silence. Say the error out loud instead.
            asyncio.create_task(voice.speak(hub, ERROR_REPLY))
    return reply
