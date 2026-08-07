"""Measure how Mackenzie actually talks, then check the endpointing settings
against that recording.

Say a couple of full sentences the way you'd really talk to Jarvis, with the
natural pauses that were getting you cut off. This replays the recording
through the exact endpointing logic and reports whether it would have cut you
off early, and what settings would fit.

    .venv/Scripts/python scripts/calibrate_mic.py
"""
import time

import numpy as np
import sounddevice as sd

from jarvis.services import ears

RATE = 16000
BLOCK = 1600
SECONDS = 14

print("Say two or three full sentences, pausing naturally between them.")
print("Talk exactly like you would to Jarvis.\n")
for i in range(3, 0, -1):
    print(f"  starting in {i}...", end="\r", flush=True)
    time.sleep(1)
print(f"  RECORDING for {SECONDS}s          ")

rec = sd.rec(int(SECONDS * RATE), samplerate=RATE, channels=1, dtype="float32")
sd.wait()
audio = rec[:, 0]
print("done.\n")

blocks = [audio[i:i + BLOCK] for i in range(0, len(audio) - BLOCK + 1, BLOCK)]
levels = np.array([float(np.sqrt(np.mean(np.square(b)))) for b in blocks])

noise = float(np.percentile(levels, 10))
speech = float(np.percentile(levels, 90))
print(f"quietest 10%  (room noise) : {noise:.5f}")
print(f"loudest  10%  (your speech): {speech:.5f}")
print(f"current start threshold    : {ears.SPEECH_RMS_THRESHOLD}")
print(f"current continue threshold : {ears.CONTINUE_RMS_THRESHOLD}")
print(f"current end-of-turn pause  : {ears.END_SILENCE_BLOCKS * 0.1:.1f}s\n")


def simulate(start_th, cont_th, end_blocks):
    """Return the number of utterances this config would have produced."""
    speaking = False
    silent_run = 0
    cuts = 0
    for lvl in levels:
        th = cont_th if speaking else start_th
        if lvl >= th:
            speaking = True
            silent_run = 0
        elif speaking:
            silent_run += 1
            if silent_run >= end_blocks:
                cuts += 1
                speaking = False
                silent_run = 0
    if speaking:
        cuts += 1
    return cuts


current = simulate(ears.SPEECH_RMS_THRESHOLD, ears.CONTINUE_RMS_THRESHOLD,
                   ears.END_SILENCE_BLOCKS)
print(f"With the current settings this recording splits into {current} utterance(s).")
print("If you spoke 2-3 sentences and this says more than that, it's still")
print("cutting you off.\n")

# suggest a continue threshold sitting between the noise floor and speech
suggested_cont = round(max(noise * 2.0, noise + (speech - noise) * 0.08), 5)
suggested_start = round(max(suggested_cont * 2.5, noise * 5), 5)
print("Suggested for your voice:")
print(f"  SPEECH_RMS_THRESHOLD   = {suggested_start}")
print(f"  CONTINUE_RMS_THRESHOLD = {suggested_cont}")
for pause in (15, 20, 25, 30):
    n = simulate(suggested_start, suggested_cont, pause)
    print(f"  END_SILENCE_BLOCKS = {pause:>2} ({pause/10:.1f}s) -> {n} utterance(s)")
print("\nTell Claude these numbers and it will set them.")
