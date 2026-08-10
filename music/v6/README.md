# AY music v6 — no-tractor pass

Duration: **170.00 seconds (2:50)**. Register timing: **50 Hz**.

V6 keeps the rounded synth attacks, noise level and overall listening level from
v5, while removing the remaining periodic machinery:

- no repeating bass noise gate;
- no repeating bass pitch grain;
- no periodic bass-volume pumping;
- no regular metallic machine tick;
- channel A is now a stable tone-only bass/drone;
- noise remains in melody attacks and the body/tail of the gentle snares.

The generated mix measures within 0.01 dB RMS of v5. Its peaks are retained
rather than flattened.

## Files

- `build_ay_recreation_v6.py` — deterministic source generator;
- `aw_intro_ay_v6_2m50s.bin.b64` — compact `AY50` register-delta source used by the
  Spectrum reel builder;
- `aw_intro_ay_v6_2m50s.vgm` — reference VGM export;
- `summary.json` — generated counts and change description.

This is a hand-arranged AY approximation. The original tracker waveform and
instrument-envelope tables are not present in the recovered source material.
