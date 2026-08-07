"""End-to-end ears test: record from the mic, gate it, transcribe it.

Exercises the exact path the HUD uses, so whatever it prints is what the
HUD would have done with the same audio.

    .venv/Scripts/python scripts/ears_test.py
"""
import time

import numpy as np
import sounddevice as sd

from jarvis.services import ears

RATE = 16000
SECONDS = 6

print("loading whisper model...")
from faster_whisper import WhisperModel  # noqa: E402

model = WhisperModel("small", device="cpu", compute_type="int8")
print("model ready\n")

print(f"SAY SOMETHING for {SECONDS} seconds (e.g. 'hey jarvis, what time is it')")
for i in range(3, 0, -1):
    print(f"  starting in {i}...", end="\r", flush=True)
    time.sleep(1)
print("  RECORDING NOW           ")

rec = sd.rec(int(SECONDS * RATE), samplerate=RATE, channels=1, dtype="float32")
sd.wait()
audio = rec[:, 0]
print("done recording\n")

peak_frame = max(
    float(np.sqrt(np.mean(np.square(audio[s:s + 1600]))))
    for s in range(0, len(audio), 1600)
)
print(f"loudest 0.1s frame RMS : {peak_frame:.5f}")
print(f"gate threshold         : {ears.SPEECH_RMS_THRESHOLD}")
gated = ears.has_speech(audio)
print(f"has_speech() verdict   : {gated}")

if not gated:
    print("\nRESULT: audio was gated out as silence -- speak louder or lower the")
    print("threshold in jarvis/services/ears.py (SPEECH_RMS_THRESHOLD).")
    raise SystemExit(1)

print("\ntranscribing...")
segments, _ = model.transcribe(audio, language="en", vad_filter=True)
text = " ".join(s.text for s in segments).strip()
print(f"TRANSCRIPT: {text!r}")

if text:
    print("\nRESULT: PIPELINE WORKS -- this text would be sent to Jarvis.")
else:
    print("\nRESULT: gate passed but whisper returned nothing.")
    print("  -> try speaking louder/closer, or set vad_filter=False in ears.py")
