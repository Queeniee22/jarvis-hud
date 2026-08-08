import asyncio

class ConnectionHub:
    # Message types that describe current state rather than a moment. Services
    # broadcast these on their own schedule -- vault every 60s, calendar every
    # 300s, and the offline notices once at startup, before any browser has
    # connected. Without a replay the first client sees empty panels and no
    # explanation, and a browser refresh waits minutes for the next cycle.
    _STATEFUL = ("status", "calendar", "vault", "graph", "vitals")

    def __init__(self):
        self._clients = set()
        self._lock = asyncio.Lock()
        self._latest = {}

    def _remember(self, message: dict):
        kind = message.get("type")
        if kind not in self._STATEFUL:
            return
        # Statuses are per-service; the rest are one-per-type.
        key = (kind, message.get("service")) if kind == "status" else (kind, None)
        self._latest[key] = message

    def snapshot(self) -> list:
        """The current state a freshly connected client has missed."""
        return list(self._latest.values())

    async def replay(self, ws):
        for message in self.snapshot():
            try:
                await ws.send_json(message)
            except Exception:
                self.remove(ws)
                return

    def add(self, ws): self._clients.add(ws)
    def remove(self, ws): self._clients.discard(ws)

    async def broadcast(self, message: dict):
        self._remember(message)
        async with self._lock:
            dead = []
            for ws in list(self._clients):
                try:
                    await ws.send_json(message)
                except Exception:
                    dead.append(ws)
            for ws in dead:
                self.remove(ws)
