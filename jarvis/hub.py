import asyncio

class ConnectionHub:
    def __init__(self):
        self._clients = set()
        self._lock = asyncio.Lock()

    def add(self, ws): self._clients.add(ws)
    def remove(self, ws): self._clients.discard(ws)

    async def broadcast(self, message: dict):
        async with self._lock:
            dead = []
            for ws in list(self._clients):
                try:
                    await ws.send_json(message)
                except Exception:
                    dead.append(ws)
            for ws in dead:
                self.remove(ws)
