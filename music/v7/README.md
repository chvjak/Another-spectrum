# AY soundtrack v7 — integrated sound effects

This version keeps the v6 no-tractor music and adds a separate SFX design layer:

- six keypad beeps with different pitches and a tiny noisy key click;
- tyre-brake squeal built from an irregular high tone sweep plus changing noise;
- alternating footsteps built from a descending low synth body and short noise tail;
- lightning strike using a three-channel crack followed by low rumble and noise decay.

Outputs include an SFX-only stem, a 17-second showcase, and the complete 2:50 mix. The native AY payload uses channel-priority stealing, so it is directly playable by the existing 50 Hz diff-stream AY routine rather than being a fourth PCM track.

The current event times are audition placements in visual scene order and are stored in `sfx_schedule.json`.
