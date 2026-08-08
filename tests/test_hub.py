import asyncio
import pytest
from jarvis.hub import ConnectionHub


@pytest.fixture
async def hub():
    """A hub whose writer tasks are always shut down, so a stalled client in
    one test can't leak a pending task into the next."""
    h = ConnectionHub()
    yield h
    await h.close()


class FakeWS:
    def __init__(self): self.sent = []
    async def send_json(self, obj): self.sent.append(obj)


class YieldingWS:
    """A socket that yields part-way through a send, like a real one."""
    def __init__(self): self.sent = []
    async def send_json(self, obj):
        await asyncio.sleep(0)
        self.sent.append(obj)


class StalledWS:
    """A socket that never completes a send until released -- a slept laptop
    with the HUD still open."""
    def __init__(self, release): self.sent = []; self._release = release
    async def send_json(self, obj):
        await self._release.wait()
        self.sent.append(obj)


async def _until(predicate, timeout=1.0):
    """Wait for a condition without draining the whole hub."""
    async def _poll():
        while not predicate():
            await asyncio.sleep(0)
    await asyncio.wait_for(_poll(), timeout)


async def test_broadcast_reaches_all_clients(hub):
    a, b = FakeWS(), FakeWS()
    hub.add(a); hub.add(b)
    await hub.broadcast({"type": "vitals", "cpu": 10})
    await hub.drain()
    assert a.sent == [{"type": "vitals", "cpu": 10}]
    assert b.sent == [{"type": "vitals", "cpu": 10}]


async def test_remove_stops_delivery(hub):
    a = FakeWS(); hub.add(a); hub.remove(a)
    await hub.broadcast({"type": "x"})
    await hub.drain()
    assert a.sent == []


async def test_broadcast_survives_and_drops_failing_client(hub):
    class BadWS:
        async def send_json(self, obj): raise RuntimeError("boom")
    good = FakeWS(); bad = BadWS()
    hub.add(good); hub.add(bad)
    await hub.broadcast({"type": "ping"})
    await hub.drain()
    assert good.sent == [{"type": "ping"}]          # healthy client still received it
    await hub.broadcast({"type": "ping2"})           # bad client was dropped
    await hub.drain()
    assert good.sent[-1] == {"type": "ping2"}


async def test_concurrent_broadcasts_do_not_interleave_sends(hub):
    """Regression: two broadcasts firing concurrently (e.g. mic + vitals)
    must not interleave ws.send_json calls on the same connection."""
    events = []

    class RecordingWS:
        async def send_json(self, obj):
            events.append(("enter", obj["type"]))
            await asyncio.sleep(0)  # yield, giving a race a chance to interleave
            events.append(("exit", obj["type"]))

    hub.add(RecordingWS())

    await asyncio.gather(
        hub.broadcast({"type": "mic"}),
        hub.broadcast({"type": "vitals"}),
    )
    await hub.drain()

    # Each broadcast's enter/exit pair must be contiguous - no other
    # broadcast's enter sneaking in between this one's enter and exit.
    assert events[0][0] == "enter"
    assert events[1] == ("exit", events[0][1])
    assert events[2][0] == "enter"
    assert events[3] == ("exit", events[2][1])
    assert {events[0][1], events[2][1]} == {"mic", "vitals"}


async def test_new_client_receives_missed_state(hub):
    """Startup offline notices fire before any browser connects; without a
    catch-up the panels sit empty with no explanation."""
    await hub.broadcast({"type": "status", "service": "calendar", "state": "offline", "detail": "no token"})
    await hub.broadcast({"type": "vault", "projects": ["Jarvis"], "threads": 2})

    late = FakeWS()
    hub.add(late)                 # registration catches it up; no separate call
    await hub.drain()

    kinds = {m["type"] for m in late.sent}
    assert kinds == {"status", "vault"}
    assert any(m.get("service") == "calendar" for m in late.sent)


async def test_replay_keeps_only_the_latest_per_service(hub):
    await hub.broadcast({"type": "status", "service": "calendar", "state": "offline", "detail": "first"})
    await hub.broadcast({"type": "status", "service": "calendar", "state": "offline", "detail": "second"})
    await hub.broadcast({"type": "status", "service": "vault", "state": "offline", "detail": "vault"})

    snap = hub.snapshot()
    cal = [m for m in snap if m.get("service") == "calendar"]
    assert len(cal) == 1 and cal[0]["detail"] == "second"
    assert len(snap) == 2, "one entry per service, not a growing log"


async def test_transient_messages_are_not_replayed(hub):
    """Amplitude and chat deltas are moments, not state -- replaying them
    would make a fresh page render a stale conversation."""
    await hub.broadcast({"type": "speak", "level": 0.5, "active": True})
    await hub.broadcast({"type": "chat", "role": "jarvis", "delta": "hi", "done": False})
    await hub.broadcast({"type": "heard", "text": "hello"})
    await hub.broadcast({"type": "mic", "level": 0.2})
    assert hub.snapshot() == []


async def test_registering_client_is_caught_up_before_live_broadcasts(hub):
    """Catch-up and the live stream share one socket. If they interleave,
    a stale snapshot lands after a fresher broadcast and the panel shows
    the older value until the next cycle -- 60s for vault, 300s for calendar."""
    await hub.broadcast({"type": "vitals", "cpu": 1})
    await hub.broadcast({"type": "status", "service": "vault", "state": "offline"})
    await hub.broadcast({"type": "graph", "nodes": [], "links": []})

    late = YieldingWS()
    hub.add(late)                                       # catch-up begins
    await hub.broadcast({"type": "vitals", "cpu": 2})    # fresher, mid-catch-up
    await hub.drain()

    seen = [m["cpu"] for m in late.sent if m["type"] == "vitals"]
    assert seen == [1, 2], f"stale catch-up clobbered live state: {seen}"


async def test_a_stalled_client_does_not_block_delivery_to_others(hub):
    """A laptop that slept with the HUD open leaves a socket that accepts
    nothing. Every service broadcast must still reach the live tab."""
    release = asyncio.Event()
    stalled, live = StalledWS(release), FakeWS()
    hub.add(stalled); hub.add(live)

    await asyncio.wait_for(hub.broadcast({"type": "vitals", "cpu": 7}), timeout=1)
    await _until(lambda: live.sent)

    assert live.sent == [{"type": "vitals", "cpu": 7}]
    assert stalled.sent == [], "the stalled socket should still be waiting"
    release.set()


async def test_a_flooded_client_keeps_the_newest_state_not_the_backlog(hub):
    """The mic broadcasts ~10x/sec. A client that stops draining must not
    hoard minutes of stale frames -- but it must not be dropped either, since
    the HUD has no reconnect and that page would be dead until a refresh."""
    release = asyncio.Event()
    stalled = StalledWS(release)
    hub.add(stalled)

    for i in range(ConnectionHub._MAX_PENDING * 3):
        await hub.broadcast({"type": "mic", "level": i})
    await hub.broadcast({"type": "vitals", "cpu": 42})

    release.set()
    await hub.drain()

    assert len(stalled.sent) <= ConnectionHub._MAX_PENDING, "backlog grew unbounded"
    assert {"type": "vitals", "cpu": 42} in stalled.sent, "newest state was lost"


async def test_close_stops_the_writers(hub):
    a = FakeWS()
    hub.add(a)
    await hub.broadcast({"type": "vitals", "cpu": 1})
    await hub.drain()

    await hub.close()
    await hub.broadcast({"type": "vitals", "cpu": 2})
    await asyncio.sleep(0)

    assert a.sent == [{"type": "vitals", "cpu": 1}]
