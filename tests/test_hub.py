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
