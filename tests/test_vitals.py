from jarvis.services.vitals import sample

def test_sample_shape(monkeypatch):
    import psutil
    monkeypatch.setattr(psutil, "cpu_percent", lambda interval=None: 42.4)
    monkeypatch.setattr(psutil, "virtual_memory", lambda: type("M", (), {"percent": 38.6})())
    monkeypatch.setattr(psutil, "disk_usage", lambda p: type("D", (), {"percent": 12.9})())
    s = sample()
    assert s == {"type": "vitals", "cpu": 42, "ram": 39, "disk": 13}
