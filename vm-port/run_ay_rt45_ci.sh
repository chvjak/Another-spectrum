#!/usr/bin/env bash
set -euo pipefail
ROOT="$PWD"; OPT="$ROOT/opt"; MUSIC="$ROOT/music-src"

cat "$OPT"/vm-port/final-perf-source.part-* | base64 -d | tar -xz -C "$OPT"
bash "$OPT/vm-port/run_rt45_ci.sh"

python3 "$MUSIC/music/v5/build_ay_recreation_v5.py"
AY50="$MUSIC/music/v5/generated/aw_intro_ay_v5_2m50s.bin"
OUT="$ROOT/out/ay-rt45"
mkdir -p "$OUT"

# Patch the standalone builder for the pinned machine layout and the observed
# 20-refresh IM2 startup. Music source tick 20 is first written on refresh 21;
# 4,103 updates then finish on refresh 8,225.
python3 - <<'PYFIX'
from pathlib import Path
p=Path('opt/vm-port/ay_rt45_build.py')
s=p.read_text()
replacements={
    'AY_UPDATES = (TICKS_50HZ + 1) // 2': 'START_TICK = 20\nAY_UPDATES = len(range(START_TICK, TICKS_50HZ, 2))',
    'for tick in range(0, TICKS_50HZ, 2):': 'for tick in range(START_TICK, TICKS_50HZ, 2):',
    '        ORG 0x{WAIT_ADDR:04X}\nay_wait_finish:': '        defs 0x{WAIT_ADDR:04X}-$,0\nay_wait_finish:',
}
for old,new in replacements.items():
    if s.count(old)!=1:
        raise SystemExit(f'AY builder marker count={s.count(old)} for {old!r}')
    s=s.replace(old,new,1)
p.write_text(s)
PYFIX

cat > "$OUT/ay-layout.json" <<'JSON'
{
  "sizes": {
    "bytecode": 9842,
    "text": 0,
    "attribute_streams": [0, 7]
  },
  "layout": {
    "bank7_tail": {"bank": 7, "offset": 9533, "bytes": 0},
    "bitmap19": {"offset": 13312, "bytes": 33}
  }
}
JSON

python3 "$OPT/vm-port/ay_rt45_build.py" \
  --base-sna "$ROOT/out/rt45/cost-4p5.sna" \
  --manifest "$OUT/ay-layout.json" \
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
       f"- AY updates: {r['ay']['ay_updates']} at 25 Hz from source tick 20 of the v5 50 Hz stream",
       f"- first AY update refresh: {r['ay']['first_ay_update_frame']}",
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
