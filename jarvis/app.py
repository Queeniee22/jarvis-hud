import asyncio

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from jarvis import config
from jarvis.hub import ConnectionHub
from jarvis.services import brain, vitals, ears, vault, voice, boot, gcal

app = FastAPI()
hub = ConnectionHub()

@app.on_event("startup")
async def _startup():
    asyncio.create_task(vitals.run(hub))
    asyncio.create_task(ears.run(hub))
    asyncio.create_task(vault.run(hub))
    asyncio.create_task(gcal.run(hub))
    # Synthesize the "thinking" fillers up front so the first one plays
    # instantly instead of paying a TTS fetch mid-pause.
    asyncio.create_task(voice.prewarm_acks())
    # Session-start: read the vault, then greet (vault CLAUDE.md protocol).
    asyncio.create_task(boot.run(hub))

@app.on_event("shutdown")
async def _shutdown():
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
                    asyncio.create_task(brain.ask(hub, text))
            elif msg.get("type") == "choice":
                # An option card was clicked. Continue the spoken conversation
                # as if he had said it, so the answer comes back by voice.
                picked = (msg.get("text") or "").strip()
                if picked:
                    await hub.broadcast({"type": "heard", "text": picked})
                    asyncio.create_task(brain.ask(hub, picked, source="voice"))
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
                path = (msg.get("path") or "").strip()
                if not path or not vault.is_known_path(path):
                    # Guard against a malformed/malicious path -- never hand
                    # an arbitrary string to the vault REST client.
                    await hub.broadcast({"type": "note_error", "path": path, "detail": "unknown note path"})
                else:
                    try:
                        content = await asyncio.to_thread(vault.read_note, path)
                        await hub.broadcast({"type": "note", "path": path, "content": content})
                    except Exception as e:
                        await hub.broadcast({"type": "note_error", "path": path, "detail": str(e)})
            elif msg.get("type") == "note_save":
                path = (msg.get("path") or "").strip()
                content = msg.get("content")
                if not path or not vault.is_known_path(path) or content is None:
                    await hub.broadcast({"type": "note_error", "path": path, "detail": "unknown note path"})
                else:
                    try:
                        await asyncio.to_thread(vault.write_note, path, content)
                        await hub.broadcast({"type": "note_saved", "path": path})
                    except Exception as e:
                        # Never log note content -- only the path and the
                        # HTTP/library error string end up anywhere.
                        await hub.broadcast({"type": "note_error", "path": path, "detail": str(e)})
    except WebSocketDisconnect:
        pass
    finally:
        # Any exit path, not just a clean disconnect -- otherwise the client
        # and its writer task leak for the life of the process.
        hub.remove(sock)
