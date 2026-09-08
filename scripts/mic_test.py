"""Live microphone level meter.

Run it, then talk. If the bar moves when you speak, the mic works and the
problem is downstream. If it stays flat while you talk, the mic itself is
muted or its input level is zero (check the physical mute button on the
Fifine, then Windows > Settings > Sound > Input > volume, or on macOS
System Settings > Sound > Input and Privacy & Security > Microphone).

    .venv/Scripts/python scripts/mic_test.py     # Windows
    .venv/bin/python scripts/mic_test.py         # macOS
"""
import sys
import time

import numpy as np
import sounddevice as sd

DURATION = 15
RATE = 16000
BLOCK = 1600  # 0.1s

device = int(sys.argv[1]) if len(sys.argv) > 1 else None
info = sd.query_devices(device if device is not None else sd.default.device[0])
print(f"listening on: {info['name']}")
print(f"talk for {DURATION} seconds...\n")

peak_seen = 0.0
loud_blocks = 0


def cb(indata, frames, t, status):
    global peak_seen, loud_blocks
    level = float(np.sqrt(np.mean(np.square(indata[:, 0]))))
    peak_seen = max(peak_seen, level)
    if level > 0.01:
        loud_blocks += 1
    bars = int(min(1.0, level * 20) * 50)
    print("\r[" + "#" * bars + "." * (50 - bars) + f"] {level:.4f}", end="", flush=True)


with sd.InputStream(device=device, channels=1, samplerate=RATE,
                    blocksize=BLOCK, callback=cb):
    time.sleep(DURATION)

print("\n")
print(f"peak level: {peak_seen:.4f}")
print(f"blocks above speech threshold: {loud_blocks}")
if peak_seen < 0.005:
    print("VERDICT: NO SIGNAL - mic is muted or input volume is 0.")
    print("  -> check the physical mute button on the Fifine (it has one)")
    print("  -> Windows Settings > Sound > Input > pick the Fifine, raise volume")
elif loud_blocks < 5:
    print("VERDICT: very quiet - mic works but gain is low. Raise input volume.")
else:
    print("VERDICT: MIC WORKS - signal is strong enough for transcription.")
