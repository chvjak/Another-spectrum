#!/usr/bin/env bash
set -euo pipefail
ROOT="$PWD"; OPT="$ROOT/opt"; MUSIC="$ROOT/music-src"

bash "$OPT/vm-port/run_rt45_ci.sh"

python3 "$MUSIC/music/v5/build_ay_recreation_v5.py"
AY50="$MUSIC/music/v5/generated/aw_intro_ay_v5_2m50s.bin"
OUT="$ROOT/out/ay-rt45"
mkdir -p "$OUT"
python3 "$OPT/vm-port/ay_rt45_build.py" \
  --base-sna "$ROOT/out/rt45/cost-4p5.sna" \
  --manifest "$OPT/vm-port/build-full/manifest.json" \
  --ay50 "$AY50" \
  --sjasmplus "$OPT/vendor-sjasmplus/sjasmplus" \
  --out "$OUT"

WASM="$OPT/vendor-jsspeccy3/dist/jsspeccy/jsspeccy-core.wasm"
node "$OPT/vm-port/ay_rt45_runner.mjs" "$WASM" \
  "$ROOT/out/rt45/cost-4p5.sna" "$OUT/cost-4p5-ay.sna" "$OUT/ay-performance-result.json"

python3 "$OPT/vm-port/ay_rt45_audio.py" "$AY50" "$OUT/another-world-ay-v5-resident-25hz-164.52s.wav" \
  --manifest "$OUT/ay-audio-manifest.json"

python3 - <<'PY'
import json
from pathlib import Path
out=Path('out/ay-rt45')
r=json.loads((out/'ay-performance-result.json').read_text())
b=json.loads((out/'ay-build-manifest.json').read_text())
lines=['# Real-time 4.5 fps build with resident AY playback','',
       f"Visual-only compute completion: **{r['baseline']['host_frames']} refreshes / {r['baseline']['seconds_at_50hz']:.2f} s**.",
       f"AY build compute completion: **{r['ay']['vm_finished_frame']} refreshes / {r['ay']['vm_finished_seconds']:.2f} s**.",
       f"Synchronized completion: **{r['ay']['host_frames']} refreshes / {r['ay']['seconds_at_50hz']:.2f} s**.",
       f"Target: **{r['target_refreshes']} refreshes / {r['target_seconds']:.2f} s**.",'',
       f"- AY updates: {r['ay']['ay_updates']} at 25 Hz from the v5 50 Hz source",
       f"- resident music/player data: {b['resident_music_bytes']} bytes",
       f"- compute margin: {r['compute_margin_refreshes']} refreshes",
       f"- final margin: {r['completion_margin_refreshes']} refreshes",
       f"- retained visuals equal: {r['frames_equal']}",
       f"- VM trace equal: {r['trace_equal']}",
       f"- passed: {r['passed']}"]
(out/'AY-RT45-RESULTS.md').write_text('\n'.join(lines)+'\n')
print('\n'.join(lines))
PY

mkdir -p "$ROOT/result/ay-rt45"
cp -f "$OUT"/* "$ROOT/result/ay-rt45/"
cp -f "$OPT/vm-port"/{ay_rt45_build.py,ay_rt45_runner.mjs,ay_rt45_audio.py,run_ay_rt45_ci.sh} "$ROOT/result/ay-rt45/"
cp -f "$MUSIC/music/v5/build_ay_recreation_v5.py" "$ROOT/result/ay-rt45/"
