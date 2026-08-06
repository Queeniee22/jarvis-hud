import asyncio
import json
import shutil

SYSTEM_PROMPT = (
    "You are Jarvis, Mackenzie's cute, terse personal assistant. "
    "Warm, direct, a little playful. Short answers; reasoning on request."
)


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


async def ask(hub, text: str):
    reply = ""
    claude_path = shutil.which("claude") or "claude"
    proc = await asyncio.create_subprocess_exec(
        claude_path, "-p", text,
        "--append-system-prompt", SYSTEM_PROMPT,
        "--output-format", "stream-json", "--verbose",
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
    )
    async for raw in proc.stdout:
        delta = parse_stream_line(raw.decode("utf-8", "ignore").strip())
        if delta:
            reply += delta
            await hub.broadcast({"type": "chat", "role": "jarvis", "delta": delta, "done": False})
    await proc.wait()
    await hub.broadcast({"type": "chat", "role": "jarvis", "delta": "", "done": True})
    return reply
