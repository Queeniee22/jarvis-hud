import asyncio

# Message types that describe current state rather than a moment. Services
# broadcast these on their own schedule -- vault every 60s, calendar every
# 300s, and the offline notices once at startup, before any browser has
# connected. Without a catch-up the first client sees empty panels and no
# explanation, and a browser refresh waits minutes for the next cycle.
# Inverted deliberately: list what is a *moment*, and treat everything else as
# state worth replaying. An opt-in list of stateful types silently failed three
# times -- calendar, the vault graph, and the skill list each broadcast once at
# startup, before any browser was listening, and the panel just sat empty with
# no error. Transients are a small, stable set; new panels are almost always
# state, so the safe default is to replay.
_TRANSIENT = (
    "hello",      # per-connection handshake
    "mic",        # live amplitude
    "speak",      # live amplitude
    "chat",       # conversation deltas -- a fresh page must not replay old talk
    "heard",      # the fading caption
    "thinking",   # tied to one in-flight turn
    "ask",        # option cards belong to the turn that raised them
    "skill",      # a single run's progress, unlike "skills" (the list)
    "note",       # opened note contents
    "note_saved",
    "note_error",
)


def _state_key(message: dict):
    """Identity of the state a message carries, or None if it is a transient
    moment (mic amplitude, chat delta) that nobody should re-render later.

    Statuses are per-service; the rest are one-per-type. This single notion of
    "is this state?" drives both the catch-up snapshot and what a backed-up
    client keeps when its backlog has to be collapsed.
    """
    kind = message.get("type")
    if not kind or kind in _TRANSIENT:
        return None
    return (kind, message.get("service")) if kind == "status" else (kind, None)


class _Client:
    """A websocket plus the messages waiting to go out on it.

    Every send for a socket goes through this one queue, drained by exactly
    one task. That is what makes two properties structural rather than a
    matter of timing: the hub is never inside send_json() twice on the same
    connection, and a client's catch-up can never land after a broadcast that
    superseded it.
    """

    def __init__(self, ws, maxsize: int):
        self.ws = ws
        self.queue = asyncio.Queue(maxsize=maxsize)
        self.task = None

    def offer(self, message: dict):
        """Queue a message, collapsing the backlog first if it is full."""
        if self.queue.full():
            self._collapse()
        try:
            self.queue.put_nowait(message)
        except asyncio.QueueFull:
            pass  # nothing left worth evicting; drop the newest instead

    def _collapse(self):
        """Keep the newest value per state, discard the transients.

        A backlog this deep means the socket is not draining -- a slept
        laptop, a wedged tab. The fix is not to drop the client (the HUD has
        no reconnect, so that page would be dead until a manual refresh) and
        not to grow without bound. It is to throw away what has been
        superseded: stale amplitude frames the client would render for one
        frame and stale state the newest value already replaces.
        """
        kept = {}
        while True:
            try:
                message = self.queue.get_nowait()
            except asyncio.QueueEmpty:
                break
            self.queue.task_done()
            key = _state_key(message)
            if key is not None:
                kept[key] = message
        for message in kept.values():
            self.queue.put_nowait(message)

    def discard_pending(self):
        """Abandon anything still queued, keeping queue.join() satisfiable."""
        while True:
            try:
                self.queue.get_nowait()
            except asyncio.QueueEmpty:
                return
            self.queue.task_done()


class ConnectionHub:
    # Deep enough to absorb a slow render, shallow enough that a wedged
    # socket collapses its backlog instead of hoarding minutes of frames.
    _MAX_PENDING = 64

    def __init__(self):
        self._clients = {}
        self._latest = {}
        # Strong references to the writer tasks. A task held only by the
        # event loop can be garbage collected mid-flight, and a removed
        # client's task still has a cancellation to process.
        self._tasks = set()

    def _remember(self, message: dict):
        key = _state_key(message)
        if key is not None:
            self._latest[key] = message

    def snapshot(self) -> list:
        """The current state a freshly connected client has missed."""
        return list(self._latest.values())

    def add(self, ws):
        """Register a client and queue the state it missed, in one step.

        The catch-up is queued before the client is reachable by any live
        broadcast, so ordering needs no lock -- a broadcast racing this call
        is simply appended behind the snapshot.
        """
        client = _Client(ws, self._MAX_PENDING)
        for message in self.snapshot():
            client.offer(message)
        self._clients[ws] = client
        client.task = asyncio.create_task(self._pump(client))
        self._tasks.add(client.task)
        client.task.add_done_callback(self._tasks.discard)

    def remove(self, ws):
        client = self._clients.pop(ws, None)
        if client is None:
            return
        task, client.task = client.task, None
        # _pump removes itself on a failed send; cancelling from inside the
        # task being cancelled would just raise back into its own handler.
        if task is not None and task is not asyncio.current_task():
            task.cancel()
        client.discard_pending()

    async def broadcast(self, message: dict):
        """Hand a message to every client. Returns once it is queued, not
        once it is delivered -- a stalled socket must not stall the others."""
        self._remember(message)
        for client in list(self._clients.values()):
            client.offer(message)

    async def drain(self):
        """Wait until everything queued has been handed to its socket."""
        await asyncio.gather(*(c.queue.join() for c in list(self._clients.values())))

    async def close(self):
        """Stop every writer. Anything still queued is abandoned."""
        for ws in list(self._clients):
            self.remove(ws)
        await asyncio.gather(*list(self._tasks), return_exceptions=True)

    async def _pump(self, client: _Client):
        """The sole writer for one socket."""
        try:
            while True:
                message = await client.queue.get()
                try:
                    await client.ws.send_json(message)
                finally:
                    client.queue.task_done()
        except asyncio.CancelledError:
            raise
        except Exception:
            self.remove(client.ws)
