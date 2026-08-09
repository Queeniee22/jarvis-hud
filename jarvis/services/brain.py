import asyncio
import json
import logging
import shutil

from jarvis import config
from jarvis.services import voice

log = logging.getLogger(__name__)

SYSTEM_PROMPT = (
    "You are Jarvis, Mackenzie's personal assistant. You are having a real "
    "spoken conversation, not writing documentation. "
    "Warm, direct, a little playful. "
    "Keep replies to one or two sentences. Speak plainly -- no markdown, no "
    "bullet lists, no code blocks, no file paths or code read aloud. "
    "Do NOT narrate or explain the changes you make. Say what you did in one "
    "short line, then stop. "
    "If something is ambiguous or you hit a problem, ask Mackenzie one short "
    "question and wait for his answer. Treat this as a back-and-forth "
    "conversation, not a report. "
    "Your working directory is Mackenzie's Obsidian vault and its CLAUDE.md "
    "is your memory protocol -- follow it. Search the vault before saying you "
    "don't know. When you learn something durable, write it to the right note: "
    "corrections Mackenzie gives you go in the 'Observed preferences' section "
    "of '01 Preferences/Working Style.md', problems and their real fixes go in "
    "'02 Programming/Debug Log.md', and anything time-bound gets appended to "
    "today's note in '05 Daily/'. Prefer updating an existing note over "
    "creating a near-duplicate. Don't announce that you wrote a note unless "
    "he asks. "
    "You can read and edit Mackenzie's files under C:\\Users\\Mackenzie, and "
    "your own source code lives in C:\\Users\\Mackenzie\\jarvis-hud -- you may "
    "change it when he asks you to improve yourself. Editing your own code "
    "does not take effect until he restarts you, so say so when you do it, "
    "and never leave your own code in a state that won't start. "
    "When you need him to choose between concrete options -- including when "
    "you are asking permission to run a command -- ask it in your spoken "
    "reply AND add a final line in exactly this form:\n"
    "ASK: <the question> :: <option one> :: <option two> :: <option three>\n"
    "Use 2 to 4 short options of a few words each. That line becomes buttons "
    "he can click, so never read it aloud or mention its format, and only "
    "use it for a real choice -- not for open questions. "
    "BEFORE running any shell command -- including tests and git -- say out "
    "loud what you intend to run and wait for Mackenzie to agree. Never run "
    "one unasked. If a command is refused, tell him what it was rather than "
    "trying a different way around it. "
    "Repeatable workflows live as notes in '06 Skills/' -- if Mackenzie asks "
    "you to run one by name, read that note and follow its '## Prompt' "
    "section. When you finish running a skill, append a short entry to that "
    "same note's '## Run log' section recording what you did and what to do "
    "differently next time."
)

# Shell access is an explicit allowlist, not a blanket grant. Headless mode
# has no way to raise an interactive permission prompt mid-turn, so this list
# IS the enforcement: anything not matched here is refused by the CLI. A
# misheard "delete the old files" cannot reach rm, del, format, or git push
# no matter how the model interprets it. The system prompt separately
# requires Jarvis to ask before running any of these.
_SAFE_BASH = [
    "Bash(pytest:*)",
    "Bash(python -m pytest:*)",
    "Bash(git status:*)",
    "Bash(git diff:*)",
    "Bash(git log:*)",
    "Bash(git add:*)",
    "Bash(git commit:*)",
]
ALLOWED_TOOLS = ",".join(["Read", "Write", "Edit", "Glob", "Grep"] + _SAFE_BASH)

# The CLI spawns fresh per turn, so without resuming a session every turn is
# amnesiac -- it could not remember the previous sentence, let alone learn.
_session_id = None


def reset_session():
    """Forget the conversation, so the next turn starts a fresh session."""
    global _session_id
    _session_id = None


ASK_PREFIX = "ASK:"
ASK_SEP = "::"


def parse_ask(reply: str):
    """Split a reply into spoken text and a clickable choice, if it has one.

    Jarvis marks a multiple-choice question with a final line like:
        ASK: Which approach? :: Rewrite it :: Patch it :: Leave it

    Returns (spoken_text, question, [options]). The marker line never reaches
    the speaker -- reading "colon colon" aloud would be absurd.
    """
    if not reply:
        return reply, None, []
    kept, question, options = [], None, []
    for line in reply.splitlines():
        stripped = line.strip()
        if question is None and stripped.upper().startswith(ASK_PREFIX):
            parts = [p.strip() for p in stripped[len(ASK_PREFIX):].split(ASK_SEP)]
            parts = [p for p in parts if p]
            if len(parts) >= 2:
                question, options = parts[0], parts[1:]
                continue  # drop the marker from the spoken text
        kept.append(line)
    return "\n".join(kept).strip(), question, options


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

    `source` is the modality the request arrived on. It decides whether the
    answer is *spoken*, not whether it is written: everything Jarvis says is
    written to the chat panel either way, so there is always a scrollback of
    his replies. What Mackenzie said is still kept out of the panel -- that
    shows as the fading caption under the waveform instead.
    """
    voice_only = source == "voice"

    async def emit(message):
        """Chat-panel output. Jarvis's side of a spoken turn is written too."""
        await hub.broadcast(message)

    # Visible for every turn, spoken or typed. The audio filler only helps if
    # you happen to be listening; this is the at-a-glance answer to "did it
    # hear me, or is it ignoring me?" during the ~5s the CLI takes.
    await hub.broadcast({"type": "thinking", "active": True})

    if voice_only:
        # Say something immediately. The CLI turn below takes ~5s of mostly
        # fixed startup, so without a filler you'd get several seconds of
        # silence and no sign it heard you.
        asyncio.create_task(voice.speak_ack(hub))

    reply = ""
    proc = None
    # Bound before the try: if create_subprocess_exec itself fails, the
    # finally block still runs and would otherwise hit UnboundLocalError.
    stderr_task = None
    cancelled = False
    claude_path = shutil.which("claude") or "claude"
    try:
        global _session_id
        args = [claude_path, "-p", text,
                "--append-system-prompt", SYSTEM_PROMPT,
                "--permission-mode", "acceptEdits",
                "--allowedTools", ALLOWED_TOOLS,
                "--output-format", "stream-json", "--verbose"]
        for extra in config.EXTRA_DIRS:
            args += ["--add-dir", extra]
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
        if not proc.returncode:
            # Report success too, not only failures. Reporting errors alone
            # leaves a healthy brain showing as "unknown" in the service
            # panel forever, which is indistinguishable from never started.
            await hub.broadcast({"type": "status", "service": "brain", "state": "online"})
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
        # Re-raising alone left the `claude` process running: cancellation
        # skips the kill in the Exception branch below, so every cancelled
        # turn orphaned a Node process for the life of the machine.
        cancelled = True
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
            # The error is in the chat panel, but a spoken turn means he may
            # not be looking at it -- raise a service status too.
            await hub.broadcast({
                "type": "status", "service": "brain", "state": "error",
                "detail": "ask failed",
            })
    finally:
        # Always reclaim the subprocess and the stderr reader, whichever way
        # we leave -- success, failure or cancellation.
        if proc is not None and proc.returncode is None:
            try:
                proc.kill()
            except ProcessLookupError:
                pass  # already gone
        if stderr_task is not None and not stderr_task.done():
            stderr_task.cancel()

        # Cleared on every exit path including cancellation -- an indicator
        # left spinning after a failed turn is worse than none at all.
        try:
            await hub.broadcast({"type": "thinking", "active": False})
        except Exception:
            log.debug("brain: could not clear the thinking indicator")

        # Guarded rather than an early `return`: returning from a finally
        # block swallows the exception on its way out, which turned a
        # cancelled turn into a silent normal return and broke shutdown.
        if not cancelled:
            await emit({"type": "chat", "role": "jarvis", "delta": "", "done": True})
            spoken, question, options = parse_ask(reply)
            if question:
                # Render clickable cards in the HUD so Mackenzie can answer
                # with a click instead of having to say the option back.
                await hub.broadcast({
                    "type": "ask", "question": question, "options": options,
                })
            if spoken:
                asyncio.create_task(voice.speak(hub, spoken))
            elif voice_only:
                # He asked out loud and there is no reply to read back. Say
                # the error rather than leaving the question hanging.
                asyncio.create_task(voice.speak(hub, ERROR_REPLY))
    return reply
