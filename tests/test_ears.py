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
