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
