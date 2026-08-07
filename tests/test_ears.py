from jarvis.services import ears

def test_mute_toggle_default_unmuted():
    ears._muted = False
    assert ears.is_muted() is False
    ears.set_muted(True)
    assert ears.is_muted() is True
    ears.set_muted(False)  # global state: leaking True mutes later tests

def test_rms_amplitude_normalized():
    import numpy as np
    block = (np.ones(1600, dtype="float32") * 0.5)
    lvl = ears.rms_level(block)
    assert 0.0 <= lvl <= 1.0 and lvl > 0.4


def test_has_speech_rejects_silence():
    import numpy as np
    assert ears.has_speech(np.zeros(16000, dtype="float32")) is False
    # room-noise floor measured on this machine (~0.0004 peak) must not pass
    assert ears.has_speech(np.full(16000, 0.0004, dtype="float32")) is False


def test_has_speech_accepts_speech_level_audio():
    import numpy as np
    assert ears.has_speech(np.full(16000, 0.2, dtype="float32")) is True


def test_has_speech_empty_is_false():
    import numpy as np
    assert ears.has_speech(np.array([], dtype="float32")) is False


def test_has_speech_accepts_quiet_mic_with_pauses():
    """Regression: a quiet mic speaking briefly inside a mostly-silent 2s
    chunk must still register. Mean-RMS gating discarded this."""
    import numpy as np
    sr = 16000
    chunk = np.zeros(2 * sr, dtype="float32")
    chunk[:int(0.4 * sr)] = (np.random.randn(int(0.4 * sr)) * 0.015).astype("float32")
    assert float(np.sqrt(np.mean(chunk ** 2))) < 0.01  # mean would fail
    assert ears.has_speech(chunk) is True               # peak-frame passes


def test_rms_level_makes_quiet_speech_visible():
    """Regression: gain of 3 rendered this mic's speech at ~2.5% bar height,
    so the waveform looked dead while the mic worked."""
    import numpy as np
    speech = np.full(1600, 0.0084, dtype="float32")   # measured speech RMS
    noise = np.full(1600, 0.0004, dtype="float32")    # measured room noise
    assert ears.rms_level(speech) > 0.15              # clearly visible
    assert ears.rms_level(noise) < 0.03               # stays flat
    assert ears.rms_level(np.full(1600, 0.05, dtype="float32")) == 1.0


def test_ptt_constants_are_sane():
    """Push-to-talk has no silence threshold to tune; only a pre-roll and a
    runaway backstop."""
    assert ears.PREROLL_BLOCKS >= 1
    assert ears.MAX_UTTERANCE_BLOCKS * 0.1 >= 30
    assert ears.PREROLL_BLOCKS >= 1
    assert ears.MAX_UTTERANCE_BLOCKS * 0.1 >= 10


def test_single_block_speech_detection():
    """The endpointing loop gates per 0.1s block, not per 2s chunk."""
    import numpy as np
    speech_block = np.full(1600, 0.0084, dtype="float32")
    silent_block = np.full(1600, 0.0004, dtype="float32")
    assert ears.has_speech(speech_block) is True
    assert ears.has_speech(silent_block) is False


async def test_holding_then_releasing_reaches_the_brain(monkeypatch):
    """End-to-end: hold, talk, release -> transcript goes to the brain.

    Releasing is what ends the turn, so no pause length is involved.
    """
    import sys, types, asyncio as aio
    import numpy as np

    captured = {}

    class FakeModel:
        def __init__(self, *a, **k): pass
        def transcribe(self, audio, **k):
            return [types.SimpleNamespace(text="hello jarvis")], None
    fw = types.ModuleType("faster_whisper")
    fw.WhisperModel = FakeModel
    monkeypatch.setitem(sys.modules, "faster_whisper", fw)

    holder = {}
    class FakeStream:
        def __init__(self, **kw): holder["cb"] = kw["callback"]
        def start(self): pass
    sd = types.ModuleType("sounddevice")
    sd.InputStream = FakeStream
    monkeypatch.setitem(sys.modules, "sounddevice", sd)

    import jarvis.services.brain as brain_mod
    async def fake_ask(hub, text, source="text"):
        captured["text"] = text
        captured["source"] = source
    monkeypatch.setattr(brain_mod, "ask", fake_ask)

    class Hub:
        def __init__(self): self.msgs = []
        async def broadcast(self, m): self.msgs.append(m)

    ears.set_muted(False)
    ears.set_ptt(False)
    hub = Hub()
    task = aio.create_task(ears.run(hub))
    await aio.sleep(0.05)

    speech = np.full((1600, 1), 0.02, dtype="float32")
    ears.set_ptt(True)                      # key down
    for _ in range(8):
        holder["cb"](speech, 1600, None, None)
    await aio.sleep(0.05)
    ears.set_ptt(False)                     # key up ends the turn

    for _ in range(60):
        await aio.sleep(0.02)
        if "text" in captured:
            break
    task.cancel()

    assert captured.get("text") == "hello jarvis"
    assert captured.get("source") == "voice"
    assert any(m.get("type") == "heard" for m in hub.msgs)


async def test_nothing_captured_while_key_is_up(monkeypatch):
    """Audio must be ignored entirely unless the key is held."""
    import sys, types, asyncio as aio
    import numpy as np

    called = {"n": 0}

    class FakeModel:
        def __init__(self, *a, **k): pass
        def transcribe(self, audio, **k):
            called["n"] += 1
            return [types.SimpleNamespace(text="should not happen")], None
    fw = types.ModuleType("faster_whisper")
    fw.WhisperModel = FakeModel
    monkeypatch.setitem(sys.modules, "faster_whisper", fw)

    holder = {}
    class FakeStream:
        def __init__(self, **kw): holder["cb"] = kw["callback"]
        def start(self): pass
    sd = types.ModuleType("sounddevice")
    sd.InputStream = FakeStream
    monkeypatch.setitem(sys.modules, "sounddevice", sd)

    class Hub:
        async def broadcast(self, m): pass

    ears.set_muted(False)
    ears.set_ptt(False)
    task = aio.create_task(ears.run(Hub()))
    await aio.sleep(0.05)

    speech = np.full((1600, 1), 0.02, dtype="float32")
    for _ in range(20):                     # talking with the key UP
        holder["cb"](speech, 1600, None, None)
    await aio.sleep(0.3)
    task.cancel()

    assert called["n"] == 0, "must not transcribe anything while the key is up"


def test_set_ptt_reports_only_real_changes():
    """Key auto-repeat must not re-trigger capture."""
    ears._q = None          # detach from any loop a prior test left behind
    ears._loop = None
    ears.set_ptt(False)
    assert ears.set_ptt(True) is True
    assert ears.set_ptt(True) is False      # repeat -> no change
    assert ears.set_ptt(False) is True
    ears.set_ptt(False)


def test_hysteresis_keeps_a_quiet_syllable_inside_the_utterance():
    """Regression: soft mid-sentence syllables fell under the single fixed
    threshold and ended the turn early, cutting Mackenzie off."""
    import numpy as np
    # a dip that is clearly speech-adjacent, not room noise
    dip = np.full(1600, 0.002, dtype="float32")
    assert ears.has_speech(dip, ears.SPEECH_RMS_THRESHOLD) is False   # would end turn
    assert ears.has_speech(dip, ears.CONTINUE_RMS_THRESHOLD) is True  # stays in turn


def test_continue_threshold_still_rejects_room_noise():
    import numpy as np
    noise = np.full(1600, 0.0004, dtype="float32")
    assert ears.has_speech(noise, ears.CONTINUE_RMS_THRESHOLD) is False


def test_thresholds_ordered():
    assert ears.CONTINUE_RMS_THRESHOLD < ears.SPEECH_RMS_THRESHOLD
