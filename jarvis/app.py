import asyncio

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from jarvis import config
from jarvis.hub import ConnectionHub
from jarvis.services import brain, vitals, ears, vault, voice

app = FastAPI()
hub = ConnectionHub()

@app.on_event("startup")
async def _startup():
    asyncio.create_task(vitals.run(hub))
    asyncio.create_task(ears.run(hub))
    asyncio.create_task(vault.run(hub))
    # Synthesize the "thinking" fillers up front so the first one plays
    # instantly instead of paying a TTS fetch mid-pause.
    asyncio.create_task(voice.prewarm_acks())

app.mount("/css", StaticFiles(directory=config.STATIC / "css"), name="css")
app.mount("/js", StaticFiles(directory=config.STATIC / "js"), name="js")
app.mount("/fonts", StaticFiles(directory=config.STATIC / "fonts"), name="fonts")

@app.get("/")
def index():
    return FileResponse(config.STATIC / "index.html")

@app.websocket("/ws")
async def ws(sock: WebSocket):
    await sock.accept()
    hub.add(sock)
    await sock.send_json({"type": "hello", "app": "jarvis"})
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
            elif msg.get("type") == "mute":
                ears.set_muted(bool(msg.get("value")))
            elif msg.get("type") == "tab":
                pass  # purely client-side; ignore server-side
    except WebSocketDisconnect:
        hub.remove(sock)
