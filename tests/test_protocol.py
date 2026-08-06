from fastapi.testclient import TestClient
from jarvis.app import app

def test_index_served():
    client = TestClient(app)
    r = client.get("/")
    assert r.status_code == 200
    assert "JARVIS" in r.text

def test_ws_accepts_and_echoes_status():
    client = TestClient(app)
    with client.websocket_connect("/ws") as ws:
        msg = ws.receive_json()
        assert msg["type"] == "hello"
