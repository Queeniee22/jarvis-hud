import math
import numpy as np

from jarvis.services import voice


def test_offline_without_key(monkeypatch):
    monkeypatch.setattr(voice.config, "ELEVENLABS_API_KEY", "")
    monkeypatch.setattr(voice.config, "VOICE_ID", "xyz")
    assert voice.available() is False


def test_offline_without_voice_id(monkeypatch):
    monkeypatch.setattr(voice.config, "ELEVENLABS_API_KEY", "abc")
    monkeypatch.setattr(voice.config, "VOICE_ID", "")
    assert voice.available() is False


def test_available_with_both(monkeypatch):
    monkeypatch.setattr(voice.config, "ELEVENLABS_API_KEY", "abc")
    monkeypatch.setattr(voice.config, "VOICE_ID", "xyz")
    assert voice.available() is True


def test_frame_levels_silence_is_near_zero():
    pcm = np.zeros(16000, dtype="float32")
    levels = voice.frame_levels(pcm, samplerate=16000, frame_sec=0.1)
    assert len(levels) == math.ceil(len(pcm) / 1600)
    assert all(lvl < 0.01 for lvl in levels)


def test_frame_levels_constant_signal_is_loud():
    pcm = np.ones(16000, dtype="float32") * 0.5
    levels = voice.frame_levels(pcm, samplerate=16000, frame_sec=0.1)
    assert len(levels) == math.ceil(len(pcm) / 1600)
    assert all(lvl > 0.4 for lvl in levels)


def test_frame_levels_partial_last_frame_counts():
    pcm = np.ones(1600 * 3 + 500, dtype="float32") * 0.5
    levels = voice.frame_levels(pcm, samplerate=16000, frame_sec=0.1)
    assert len(levels) == math.ceil(len(pcm) / 1600)


async def test_playback_failure_reports_status_and_clears_sphere(monkeypatch):
    """sd.play() blowing up must not escape into brain's fire-and-forget task."""
    import numpy as np
    monkeypatch.setattr(voice.config, "ELEVENLABS_API_KEY", "abc")
    monkeypatch.setattr(voice.config, "VOICE_ID", "xyz")
    monkeypatch.setattr(voice, "_fetch_pcm", lambda text: np.zeros(1600, dtype="float32"))

    import sys, types
    fake_sd = types.ModuleType("sounddevice")
    def boom(*a, **k):
        raise RuntimeError("no output device")
    fake_sd.play = boom
    monkeypatch.setitem(sys.modules, "sounddevice", fake_sd)

    class StubHub:
        def __init__(self): self.msgs = []
        async def broadcast(self, m): self.msgs.append(m)

    h = StubHub()
    await voice.speak(h, "hello")  # must not raise

    errors = [m for m in h.msgs if m.get("type") == "status" and m.get("state") == "error"]
    assert errors, "playback failure should broadcast an error status"
    assert h.msgs[-1] == {"type": "speak", "level": 0.0, "active": False}
