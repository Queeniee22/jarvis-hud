from jarvis.services import ears

def test_mute_toggle_default_unmuted():
    ears._muted = False
    assert ears.is_muted() is False
    ears.set_muted(True)
    assert ears.is_muted() is True

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


def test_endpoint_constants_are_sane():
    """Endpointing must react well under a second but tolerate real pauses."""
    assert 0.3 <= ears.END_SILENCE_BLOCKS * 0.1 <= 1.0
    assert ears.PREROLL_BLOCKS >= 1
    assert ears.MAX_UTTERANCE_BLOCKS * 0.1 >= 10


def test_single_block_speech_detection():
    """The endpointing loop gates per 0.1s block, not per 2s chunk."""
    import numpy as np
    speech_block = np.full(1600, 0.0084, dtype="float32")
    silent_block = np.full(1600, 0.0004, dtype="float32")
    assert ears.has_speech(speech_block) is True
    assert ears.has_speech(silent_block) is False
