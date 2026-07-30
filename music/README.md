# AY soundtrack experiments

This branch combines the recovered `diff-stream/` intro work with the preserved AY soundtrack generators.

## Versions

- `v4/` — noisier baseline: strong machine modulation, sampled-style melody attacks, gentle body-plus-noise snares.
- `v5/` — current version: retains the noise and long-term level, reduces the regular “tractor” pulse, rounds the synth attacks, and lowers transient peaks by about 3 dB.

Both versions generate a 2:50 soundtrack at 50 AY register updates per second. Run:

```sh
python3 music/v4/build_ay_recreation_v4.py
python3 music/v5/build_ay_recreation_v5.py
```

Requirements: Python 3, NumPy, SciPy and ffmpeg.

Generated output includes MP3/FLAC previews, three stems, a compact `AY50` register-delta stream, VGM/VGZ and a complete register CSV. Generated media is ignored by Git and is not committed.

## Integration status

The music source and diff-stream source now coexist on this branch, but the existing diff-stream snapshot builder does not yet call the AY50 decoder from its interrupt handler. The intended integration is one AY update per 50 Hz interrupt and two AY updates per 25 fps video frame. The old diff-stream timing bug must be corrected before final soundtrack synchronization.
