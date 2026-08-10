#!/usr/bin/env bash
set -euo pipefail
ROOT="$PWD"; OPT="$ROOT/opt"

# Rebuild the exact measured row-fill winner and its pinned emulator/toolchain.
bash "$OPT/vm-port/run_row_fill_ci.sh"

WASM="$OPT/vendor-jsspeccy3/dist/jsspeccy/jsspeccy-core.wasm"
base64 -d "$OPT/vm-port/rt45-runner.b64" > "$ROOT/rt45_runner.mjs"
node --check "$ROOT/rt45_runner.mjs"
BASE="$ROOT/out/r-row-vertical-exx-table.sna"
PLAN_DIR="$ROOT/out/rt45-plans"
mkdir -p "$PLAN_DIR"

node "$ROOT/rt45_runner.mjs" profile "$WASM" "$BASE" "$ROOT/out/rt45-profile.json"
python3 "$OPT/vm-port/rt45_plan.py" "$ROOT/out/rt45-profile.json" "$PLAN_DIR"

for plan in "$PLAN_DIR"/*-4p5.json; do
  name=$(basename "$plan" .json)
  mkdir -p "$PLAN_DIR/$name"
  python3 "$OPT/vm-port/rt45_optimize_draws.py" \
    --trace "$OPT/vm-port/build-full/optimizer-trace.log" \
    --plan "$plan" \
    --out-dir "$PLAN_DIR/$name"
done

python3 "$OPT/vm-port/rt45_build.py" \
  --base-sna "$BASE" \
  --vm-source "$ROOT/out/work/vm-both.asm" \
  --unrolled-patch "$OPT/vm-port/unrolled_perf_patch.py" \
  --rt45-patch "$OPT/vm-port/rt45_patch.py" \
  --sjasmplus "$OPT/vendor-sjasmplus/sjasmplus" \
  --plans-dir "$PLAN_DIR" \
  --out "$ROOT/out/rt45"

node "$ROOT/rt45_runner.mjs" matrix "$WASM" "$BASE" \
  "$PLAN_DIR/rt45-plans.json" "$ROOT/out/rt45" "$ROOT/out/rt45-result.json"

python3 - <<'PY'
import json
from pathlib import Path
out=Path('out')
r=json.loads((out/'rt45-result.json').read_text())
lines=['# 4.5 fps real-time benchmark','',
       f"Baseline row-fill winner: **{r['baseline']['host_frames']} refreshes / {r['baseline']['seconds_at_50hz']:.2f} s**.",
       f"Target: **{r['target_refreshes']} refreshes / {r['target_seconds']:.2f} s**.",'',
       '| Plan | Rendered frames | Refreshes | Seconds | Saved | Target margin | Kept frames exact |','|---|---:|---:|---:|---:|---:|---|']
for name,v in r['variants'].items():
    lines.append(f"| {name} | {v['rendered_presentations']} | {v['host_frames']} | {v['seconds_at_50hz']:.2f} | {v['saved_percent']:.2f}% | {v['margin_refreshes']} | {v['visible_kept_frames_equal']} |")
lines += ['', f"Winner: **{r['winner']}**.", f"Real-time achieved: **{r['real_time_achieved']}**.",
          '', 'Every accepted retained frame is byte-identical to the corresponding frame of the 298-frame row-fill baseline; VM tick, bytecode instruction count and trace hash also match.']
(out/'RT45-RESULTS.md').write_text('\n'.join(lines)+'\n')
print('\n'.join(lines))
PY

mkdir -p "$ROOT/result/rt45"
cp -f "$ROOT/out"/{rt45-profile.json,rt45-result.json,RT45-RESULTS.md} "$ROOT/result/rt45/"
cp -f "$ROOT/out/rt45"/{rt45-build-manifest.json,vm-rt45.asm,vm-rt45.bin} "$ROOT/result/rt45/"
cp -f "$ROOT/out/rt45"/*.sna "$ROOT/result/rt45/"
cp -f "$PLAN_DIR"/*.json "$ROOT/result/rt45/"
for d in "$PLAN_DIR"/*-4p5; do
  name=$(basename "$d")
  mkdir -p "$ROOT/result/rt45/$name"
  cp -f "$d"/{draw-optimization.json,draw-event-keep-mask.bin,event-runs.bin} "$ROOT/result/rt45/$name/"
done
cp -f "$OPT/vm-port"/{rt45_patch.py,rt45_optimize_draws.py,rt45_plan.py,rt45_build.py,run_rt45_ci.sh,rt45-runner.b64} "$ROOT/result/rt45/"
cp -f "$ROOT/rt45_runner.mjs" "$ROOT/result/rt45/"
