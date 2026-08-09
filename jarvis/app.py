import asyncio

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from jarvis import config
from jarvis.hub import ConnectionHub
from jarvis.services import brain, vitals, ears, vault, voice, boot, gcal

app = FastAPI()
hub = ConnectionHub()

# The event loop holds only *weak* references to tasks, so a service whose
# task object is discarded can be garbage-collected mid-run and simply stop.
# Keeping them here also gives shutdown something to cancel.
_service_tasks: set[asyncio.Task] = set()


def _spawn(coro):
    task = asyncio.create_task(coro)
    _service_tasks.add(task)
    task.add_done_callback(_service_tasks.discard)
    return task


@app.on_event("startup")
async def _startup():
    _spawn(vitals.run(hub))
    _spawn(ears.run(hub))
    _spawn(vault.run(hub))
    _spawn(gcal.run(hub))
    # Synthesize the "thinking" fillers up front so the first one plays
    # instantly instead of paying a TTS fetch mid-pause.
    _spawn(voice.prewarm_acks(hub))
    # Session-start: read the vault, then greet (vault CLAUDE.md protocol).
    _spawn(boot.run(hub))

@app.on_event("shutdown")
async def _shutdown():
    # Stop the services before the clients: a service mid-broadcast against a
    # closing hub would raise into its own task on the way down.
    for task in list(_service_tasks):
        task.cancel()
    if _service_tasks:
        await asyncio.gather(*_service_tasks, return_exceptions=True)
    await hub.close()

app.mount("/css", StaticFiles(directory=config.STATIC / "css"), name="css")
app.mount("/js", StaticFiles(directory=config.STATIC / "js"), name="js")
app.mount("/fonts", StaticFiles(directory=config.STATIC / "fonts"), name="fonts")

@app.middleware("http")
async def _no_cache(request, call_next):
    """Never let the browser cache the HUD.

    A stale cached hud.js silently keeps running the previous build -- which
    looked exactly like "push-to-talk doesn't work" while the server side was
    fine. Not worth caching a local single-user page.
    """
    response = await call_next(request)
    response.headers["Cache-Control"] = "no-store, must-revalidate"
    response.headers["Pragma"] = "no-cache"
    return response


async def _open_note(path: str):
    # The guard re-lists the vault on a miss, so it can block; it belongs on
    # this task rather than in the websocket receive loop.
    if not path or not await asyncio.to_thread(vault.is_known_path, path):
        await hub.broadcast({"type": "note_error", "path": path, "detail": "unknown note path"})
        return
    try:
        content = await asyncio.to_thread(vault.read_note, path)
        await hub.broadcast({"type": "note", "path": path, "content": content})
    except Exception as e:
        await hub.broadcast({"type": "note_error", "path": path, "detail": str(e)})


async def _save_note(path: str, content):
    if not path or content is None or not await asyncio.to_thread(vault.is_known_path, path):
        await hub.broadcast({"type": "note_error", "path": path, "detail": "unknown note path"})
        return
    try:
        await asyncio.to_thread(vault.write_note, path, content)
        await hub.broadcast({"type": "note_saved", "path": path})
    except Exception as e:
        # Never log note content -- only the path and the error string.
        await hub.broadcast({"type": "note_error", "path": path, "detail": str(e)})


@app.get("/")
def index():
    return FileResponse(config.STATIC / "index.html")

@app.websocket("/ws")
async def ws(sock: WebSocket):
    await sock.accept()
    # Say hello before registering: from add() onward the hub owns this
    # socket and is the only thing allowed to write to it.
    await sock.send_json({"type": "hello", "app": "jarvis"})
    # Registering also queues the state this client missed -- services
    # broadcast on slow cycles, and the startup offline notices fire before
    # anyone is listening.
    hub.add(sock)
    try:
        while True:
            try:
                msg = await sock.receive_json()
            except WebSocketDisconnect:
                raise
            except Exception:
                continue  # ignore malformed frames, keep the connection
            if msg.get("type") == "say":
                text = (msg.get("text") or "").strip()
                if text:
                    await hub.broadcast({"type": "chat", "role": "you", "delta": text, "done": True})
                    _spawn(brain.ask(hub, text))
            elif msg.get("type") == "choice":
                # An option card was clicked. Continue the spoken conversation
                # as if he had said it, so the answer comes back by voice.
                picked = (msg.get("text") or "").strip()
                if picked:
                    await hub.broadcast({"type": "heard", "text": picked})
                    _spawn(brain.ask(hub, picked, source="voice"))
            elif msg.get("type") == "ptt":
                active = bool(msg.get("value"))
                if active and voice.is_speaking():
                    # Starting to talk interrupts Jarvis -- that is what
                    # reaching for the key means.
                    voice.stop_speaking()
                    await hub.broadcast({"type": "speak", "level": 0.0, "active": False})
                ears.set_ptt(active)
            elif msg.get("type") == "mute":
                ears.set_muted(bool(msg.get("value")))
            elif msg.get("type") == "tab":
                pass  # purely client-side; ignore server-side
            elif msg.get("type") == "note_open":
                # Spawned, not awaited: a vault round-trip inline here would
                # stall this loop, and the next message might be the
                # push-to-talk release. Reading a note must not delay speech.
                _spawn(_open_note((msg.get("path") or "").strip()))
            elif msg.get("type") == "note_save":
                _spawn(_save_note((msg.get("path") or "").strip(), msg.get("content")))
    except WebSocketDisconnect:
        pass
    finally:
        # Any exit path, not just a clean disconnect -- otherwise the client
        # and its writer task leak for the life of the process.
        hub.remove(sock)
