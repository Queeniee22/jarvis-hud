import asyncio

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from jarvis import config
from jarvis.hub import ConnectionHub
from jarvis.services import vitals

app = FastAPI()
hub = ConnectionHub()

@app.on_event("startup")
async def _startup():
    asyncio.create_task(vitals.run(hub))

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
            await sock.receive_json()  # client messages handled in later phases
    except WebSocketDisconnect:
        hub.remove(sock)
