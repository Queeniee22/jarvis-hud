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


async def test_speak_ack_uses_cache_and_does_not_refetch(monkeypatch):
    """The filler must play instantly; a TTS fetch mid-pause defeats it."""
    import numpy as np
    monkeypatch.setattr(voice.config, "ELEVENLABS_API_KEY", "abc")
    monkeypatch.setattr(voice.config, "VOICE_ID", "xyz")
    calls = []
    def fake_fetch(text):
        calls.append(text)
        return np.zeros(1600, dtype="float32")
    monkeypatch.setattr(voice, "_fetch_pcm", fake_fetch)
    monkeypatch.setattr(voice, "_quota_gone", False, raising=False)
    monkeypatch.setattr(voice, "_ack_cache", {}, raising=False)

    played = []
    async def fake_play(hub, pcm, samplerate=16000): played.append(pcm)
    monkeypatch.setattr(voice, "_play", fake_play)

    class Hub:
        async def broadcast(self, m): pass

    await voice.speak_ack(Hub())
    assert len(calls) == 1 and len(played) == 1
    # every subsequent ack for a cached phrase must hit the cache
    for _ in range(len(voice.ACK_PHRASES) * 4):
        await voice.speak_ack(Hub())
    assert len(calls) <= len(voice.ACK_PHRASES), "acks should be cached, not refetched"


async def test_ack_phrases_are_short(monkeypatch):
    """Fillers must finish inside the brain's ~5s turn."""
    for p in voice.ACK_PHRASES:
        assert len(p.split()) <= 4, f"{p!r} is too long for a filler"


def test_half_duplex_gate_and_barge_in(monkeypatch):
    """Mic must be held while Jarvis is audible, and release on interrupt."""
    import time as _t
    voice._speaking = False
    voice._speaking_until = 0.0
    assert voice.is_speaking() is False

    voice._speaking = True
    assert voice.is_speaking() is True, "mic must be gated while speaking"

    # tail keeps the gate closed briefly after playback ends
    voice._speaking = False
    voice._speaking_until = _t.monotonic() + 5
    assert voice.is_speaking() is True, "tail should cover speaker ring-out"

    # barge-in clears everything immediately
    voice.stop_speaking()
    assert voice.is_speaking() is False, "interrupt must reopen the mic at once"


def test_quota_exhaustion_is_recognised_not_mistaken_for_a_bad_key():
    """ElevenLabs returns 401 for an exhausted quota, which reads as an auth
    failure and sent this project hunting for a broken API key. The body is
    what actually distinguishes the two."""
    from jarvis.services import voice

    class QuotaResp:
        status_code = 401
        def json(self):
            return {"detail": {"status": "quota_exceeded", "code": "quota_exceeded",
                               "message": "You have 0 credits remaining"}}

    class BadKeyResp:
        status_code = 401
        def json(self):
            return {"detail": "Invalid API key"}

    assert voice._is_quota_error(QuotaResp()) is True
    assert voice._is_quota_error(BadKeyResp()) is False


def test_a_real_auth_failure_is_not_treated_as_quota():
    from jarvis.services import voice

    class Resp:
        status_code = 403
        def json(self): return {"detail": {"status": "forbidden"}}

    assert voice._is_quota_error(Resp()) is False


async def test_speech_falls_back_to_the_local_voice_when_credits_run_out(monkeypatch):
    """Going silent because a monthly quota ran out is a bad failure mode for
    an assistant you talk to."""
    import numpy as np
    from jarvis.services import voice

    monkeypatch.setattr(voice.config, "ELEVENLABS_API_KEY", "abc")
    monkeypatch.setattr(voice.config, "VOICE_ID", "xyz")
    monkeypatch.setattr(voice, "_quota_gone", False, raising=False)

    def out_of_credits(text):
        raise voice.QuotaExhausted("no credits")
    monkeypatch.setattr(voice, "_fetch_pcm", out_of_credits)

    local_calls = []
    def fake_local(text):
        local_calls.append(text)
        return np.zeros(2205, dtype="float32"), 22050
    monkeypatch.setattr(voice, "_local_pcm", fake_local)

    class Hub:
        def __init__(self): self.msgs = []
        async def broadcast(self, m): self.msgs.append(m)

    hub = Hub()
    pcm, rate = await voice.synthesize(hub, "hello")

    assert pcm is not None, "must still produce audio"
    assert rate == 22050, "the local voice's own sample rate must be carried"
    assert local_calls == ["hello"]
    degraded = [m for m in hub.msgs if m.get("state") == "degraded"]
    assert degraded, "the HUD must say the voice is degraded, not silently switch"


async def test_the_cloud_is_not_retried_once_the_quota_is_known_gone(monkeypatch):
    """The quota does not come back this month; a failed round-trip before
    every line is pure latency."""
    import numpy as np
    from jarvis.services import voice

    monkeypatch.setattr(voice.config, "ELEVENLABS_API_KEY", "abc")
    monkeypatch.setattr(voice.config, "VOICE_ID", "xyz")
    monkeypatch.setattr(voice, "_quota_gone", True, raising=False)

    cloud_calls = []
    monkeypatch.setattr(voice, "_fetch_pcm", lambda t: cloud_calls.append(t))
    monkeypatch.setattr(voice, "_local_pcm",
                        lambda t: (np.zeros(100, dtype="float32"), 22050))

    class Hub:
        async def broadcast(self, m): pass

    await voice.synthesize(Hub(), "hi")
    assert cloud_calls == [], "must not call ElevenLabs again once quota is gone"


async def test_local_failure_too_reports_an_error_rather_than_hanging(monkeypatch):
    from jarvis.services import voice

    monkeypatch.setattr(voice.config, "ELEVENLABS_API_KEY", "")
    monkeypatch.setattr(voice.config, "VOICE_ID", "")
    def boom(text):
        raise RuntimeError("no audio device")
    monkeypatch.setattr(voice, "_local_pcm", boom)

    class Hub:
        def __init__(self): self.msgs = []
        async def broadcast(self, m): self.msgs.append(m)

    hub = Hub()
    pcm, rate = await voice.synthesize(hub, "hi")
    assert pcm is None and rate is None
    assert any(m.get("state") == "error" for m in hub.msgs)
