#!/usr/bin/env bash
set -euo pipefail
ROOT="$PWD"; OPT="$ROOT/opt"; MUSIC="$ROOT/music-src"

cat "$OPT"/vm-port/final-perf-source.part-* | base64 -d | tar -xz -C "$OPT"
bash "$OPT/vm-port/run_rt45_ci.sh"

python3 "$MUSIC/music/v5/build_ay_recreation_v5.py"
AY50="$MUSIC/music/v5/generated/aw_intro_ay_v5_2m50s.bin"
OUT="$ROOT/out/ay-rt45"
mkdir -p "$OUT"

# The VM owns the 0x93xx scratch block. Move every AY state byte into unused,
# always-visible bank-5 RAM at 0x7C00. Keep all 4,113 even source updates; with
# the first interrupt update observed on refresh 2, the last lands on 8,226.
python3 - <<'PYFIX'
from pathlib import Path
p=Path('opt/vm-port/ay_rt45_build.py')
s=p.read_text()
old_block='''AY_INIT = 0x93EA
AY_PHASE = 0x93EB
AY_REMAIN = 0x93EC
AY_PTR = 0x93EE
AY_SEG_END = 0x93F0
AY_SEG_BANK = 0x93F2
AY_SEG_TABLE_PTR = 0x93F3
AY_FLAG_PTR = 0x93F5
AY_FLAG_BYTE = 0x93F7
AY_FLAG_BITS = 0x93F8
AY_SAVED_PAGE = 0x93F9
AY_UPDATE_COUNT = 0x93FA
AY_VM_FINISHED = 0x93FC
'''
new_block='''AY_INIT = 0x7C00
AY_PHASE = 0x7C01
AY_REMAIN = 0x7C02
AY_PTR = 0x7C04
AY_SEG_END = 0x7C06
AY_SEG_BANK = 0x7C08
AY_SEG_TABLE_PTR = 0x7C09
AY_FLAG_PTR = 0x7C0B
AY_FLAG_BYTE = 0x7C0D
AY_FLAG_BITS = 0x7C0E
AY_SAVED_PAGE = 0x7C0F
AY_UPDATE_COUNT = 0x7C10
AY_VM_FINISHED = 0x7C12
'''
replacements={
    old_block: new_block,
    '        (0xFF, HANDLER_LIMIT, 0x8000),': '        (0xFF, 0x7C20, 0x8000),',
    '        ORG 0x{WAIT_ADDR:04X}\nay_wait_finish:': '        defs 0x{WAIT_ADDR:04X}-$,0\nay_wait_finish:',
    '''    state_start = bank_offset(2) + (AY_INIT - 0x8000)
    state_bytes = AY_VM_FINISHED + 1 - AY_INIT
    snapshot[state_start:state_start + state_bytes] = b"\\x00" * state_bytes
''': '''    state_start = bank_offset(5) + (AY_INIT - 0x4000)
    state_bytes = AY_VM_FINISHED + 1 - AY_INIT
    if any(snapshot[state_start:state_start + state_bytes]):
        raise RuntimeError("AY fixed-bank state target is not empty")
    snapshot[state_start:state_start + state_bytes] = b"\\x00" * state_bytes
''',
}
for old,new in replacements.items():
    if s.count(old)!=1:
        raise SystemExit(f'AY builder marker count={s.count(old)} for {old[:80]!r}')
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
       f"- AY updates: {r['ay']['ay_updates']} at 25 Hz from the v5 50 Hz source",
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
