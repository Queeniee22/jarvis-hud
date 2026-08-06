import asyncio
import pytest
from jarvis.hub import ConnectionHub

class FakeWS:
    def __init__(self): self.sent = []
    async def send_json(self, obj): self.sent.append(obj)

@pytest.mark.asyncio
async def test_broadcast_reaches_all_clients():
    hub = ConnectionHub()
    a, b = FakeWS(), FakeWS()
    hub.add(a); hub.add(b)
    await hub.broadcast({"type": "vitals", "cpu": 10})
    assert a.sent == [{"type": "vitals", "cpu": 10}]
    assert b.sent == [{"type": "vitals", "cpu": 10}]

@pytest.mark.asyncio
async def test_remove_stops_delivery():
    hub = ConnectionHub()
    a = FakeWS(); hub.add(a); hub.remove(a)
    await hub.broadcast({"type": "x"})
    assert a.sent == []

@pytest.mark.asyncio
async def test_broadcast_survives_and_drops_failing_client():
    class BadWS:
        async def send_json(self, obj): raise RuntimeError("boom")
    hub = ConnectionHub()
    good = FakeWS(); bad = BadWS()
    hub.add(good); hub.add(bad)
    await hub.broadcast({"type": "ping"})
    assert good.sent == [{"type": "ping"}]          # healthy client still received it
    await hub.broadcast({"type": "ping2"})           # bad client was dropped
    assert good.sent[-1] == {"type": "ping2"}
