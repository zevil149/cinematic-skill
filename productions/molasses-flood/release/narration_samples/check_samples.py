#!/usr/bin/env python3
"""Check the six sample recordings in incoming/ (read-only: nothing is copied, converted or moved).

  python3 productions/molasses-flood/release/narration_samples/check_samples.py

For each of L0001, L0008, L0024, L0037, L0041, L0046: present?, 16-bit PCM WAV?, mono?, sample rate,
duration (and its ratio to the scratch voice), RMS level, peak (clipping). Uses the same reader the
pipeline uses for manual recordings (voices.wav_info) and the same minimums (voice.py).
"""
import json
import pathlib
import sys
import wave

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parents[3]
sys.path.insert(0, str(ROOT / "skills" / "cinematic-film" / "scripts"))
import voice as VO  # noqa: E402
import voices as V  # noqa: E402

LINES = (1, 8, 24, 37, 41, 46)
timing = {s["id"]: s for s in json.loads((HERE.parents[1] / "editions/hi/audio/timing.json").read_text())["segments"]}
bad = 0
for i in LINES:
    f = HERE / "incoming" / f"L{i:04d}.wav"
    if not f.exists():
        print(f"L{i:04d}: missing"); bad += 1; continue
    try:
        with wave.open(str(f)) as w:
            ch = w.getnchannels()
        dur, rate, rms, peak = V.wav_info(f)
    except Exception as e:                                  # noqa: BLE001
        print(f"L{i:04d}: not a readable 16-bit PCM WAV ({e})"); bad += 1; continue
    notes = []
    if ch != 1:
        notes.append(f"{ch} channels (record or export mono)")
    if rate < 44100:
        notes.append(f"{rate} Hz (44.1 or 48 kHz recommended)")
    if dur < VO.MIN_SECONDS or rms < VO.MIN_RMS:
        notes.append("too short or too quiet for the pipeline")
    if peak >= VO.CLIP_PEAK:
        notes.append("clipped (peak at full scale): record lower")
    elif rms < 0.03:
        notes.append("quiet (RMS below 0.03): record closer or a little louder")
    ratio = dur / timing[i]["duration"]
    print(f"L{i:04d}: {dur:.2f}s ({ratio:.2f}x scratch), {rate} Hz, {ch} ch, RMS {rms:.3f}, peak {peak:.2f}"
          + (" — " + "; ".join(notes) if notes else " — ok"))
    bad += bool(notes)
print("all six ok" if not bad else f"{bad} file(s) need attention")
sys.exit(1 if bad else 0)
