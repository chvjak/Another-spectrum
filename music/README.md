# AY soundtrack experiments

This branch combines the recovered `diff-stream/` intro work with versioned AY soundtrack generators.

## Versions

- `v4/` — noisy baseline with strong machine modulation, sampled-style melody attacks, and gentle body-plus-noise snares.
- `v5/` — rounded attacks and reduced machine pulse.
- `v6/` — removes the tractor effect completely while retaining v5 synth peaks, noise character and long-term level.
- `v7/` — current version: keeps the v6 music and adds keypad beeps, tyre-brake squeal, footsteps and lightning using AY tone plus noise.

All versions generate a 2:50 soundtrack at 50 AY register updates per second. Run:

```sh
python3 music/v4/build_ay_recreation_v4.py
python3 music/v5/build_ay_recreation_v5.py
python3 music/v6/build_ay_recreation_v6.py
python3 music/v7/build_ay_sfx_v7.py
```

Requirements: Python 3 and NumPy for the native AY payload generators. The richer preview generators additionally use SciPy and ffmpeg.

Generated MP3/FLAC previews, stems, VGM/VGZ and register CSV files are written below each version's `generated/` directory and ignored by Git. The committed v7 `AY50` payload is Base64-wrapped compressed text so the diff-stream builder can consume it directly without generated media in Git.

## Integration status

`diff-stream/build_full_speccy.py` defaults to v7 and advances AY once per 50 Hz `HALT`. With `SPECCY_WAIT_FRAMES=2`, each 25 fps visual frame receives exactly two AY updates. Each snapshot reel begins with a full AY register state, so reel boundaries are independently restartable. SFX are already merged into the native three-channel register stream using priority channel stealing.
