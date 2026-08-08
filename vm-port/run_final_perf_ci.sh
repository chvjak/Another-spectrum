#!/usr/bin/env bash
set -euo pipefail
ROOT="$PWD"
OPT="$ROOT/opt"

# Recreate the exact measured EGA-copy worktree, resources, assembler and core.
# The EGA runner first materializes its generated sources. Inject the same
# relocation patch used by the successful measured workflow immediately after
# that extraction, before any generated source is assembled.
python3 - <<'PYFIX'
from pathlib import Path
p = Path('opt/vm-port/run_ega_ci.sh')
s = p.read_text()
marker = 'cat "$OPT"/vm-port/ega-source.part-* | base64 -d | tar -xz -C "$OPT"\n'
if marker not in s:
    raise SystemExit('EGA source-extraction marker changed')
s = s.replace(marker, marker + 'git -C "$OPT" apply vm-port/ega-profile-relocate.patch\n', 1)
p.write_text(s)
PYFIX
bash "$OPT/vm-port/run_ega_ci.sh"

SJASM="$OPT/vendor-sjasmplus/sjasmplus"
WASM="$OPT/vendor-jsspeccy3/dist/jsspeccy/jsspeccy-core.wasm"
WORK="$ROOT/out/work"
OUT="$ROOT/out"
PATCH="$OPT/vm-port/final_perf_patch.py"

python3 "$OPT/vm-port/final_perf_build.py" trace \
  --work "$WORK" --patch "$PATCH" --sjasmplus "$SJASM" --out "$OUT"
node "$OPT/vm-port/final_perf_runner.mjs" trace "$WASM" "$OUT"
python3 "$OPT/vm-port/final_generate_restore_script.py" \
  "$OUT/restore-trace.json" "$OUT/restore-script.bin" "$OUT/restore-script-meta.json"
python3 "$OPT/vm-port/final_perf_build.py" variants \
  --work "$WORK" --patch "$PATCH" --sjasmplus "$SJASM" --out "$OUT" \
  --script "$OUT/restore-script.bin"
node "$OPT/vm-port/final_perf_runner.mjs" matrix "$WASM" "$OUT" \
  ega-best script-table-ldi-lazy combined || true
cp "$OUT/final-perf-result.json" "$OUT/final-perf-invalid-variants.json"
node "$OPT/vm-port/final_perf_runner.mjs" matrix "$WASM" "$OUT" \
  ega-best restore script-arith script-table script-table-ldi
cp "$OUT/final-perf-result.json" "$OUT/final-perf-matrix-before-elision.json"

# Exact output-driven removal of complete restore calls and character rows.
node "$OPT/vm-port/final_perf_runner.mjs" elide "$WASM" "$OUT" \
  "$OUT/restore-script-meta.json" "$OUT/restore-script.bin" 120
node "$OPT/vm-port/final_perf_runner.mjs" matrix "$WASM" "$OUT" ega-best script-table-ldi final
cp "$OUT/final-perf-result.json" "$OUT/final-perf-result-final.json"

python3 - <<'PY'
import json
from pathlib import Path
out=Path('out')
pre=json.loads((out/'final-perf-matrix-before-elision.json').read_text())
fin=json.loads((out/'final-perf-result-final.json').read_text())
build=json.loads((out/'final-variants-build-manifest.json').read_text())
elide=json.loads((out/'restore-elision-result.json').read_text())
lines=['# Final performance experiment','', '| Variant | Refreshes | Seconds | Vs EGA best |','|---|---:|---:|---:|']
ref=pre['runs']['ega-best']['host_frames']
for label,run in pre['runs'].items():
    lines.append(f"| {label} | {run['host_frames']} | {run['seconds_at_50hz']:.2f} | {(1-run['host_frames']/ref)*100:.2f}% |")
run=fin['runs']['final']
lines += ['', f"Final: **{run['host_frames']} refreshes / {run['seconds_at_50hz']:.2f} s**.",
          f"Target 164.52 s; ratio {run['seconds_at_50hz']/164.52:.4f}x.",
          f"Elided calls: {elide['elided_calls']}; elided row groups: {elide['elided_row_runs']}; optimizer tests: {elide['tests']}.",
          '', 'All accepted variants must match the visible 298-presentation screen sequence, VM trace, primitive count and error-free completion.']
(out/'FINAL-PERF-RESULTS.md').write_text('\n'.join(lines)+'\n')
print('\n'.join(lines))
PY

mkdir -p result
cp -f "$OUT"/{FINAL-PERF-RESULTS.md,final-perf-matrix-before-elision.json,final-perf-invalid-variants.json,final-perf-result-final.json,restore-elision-result.json,restore-trace.json,restore-script.bin,restore-script-elided.bin,restore-script-meta.json,final-trace-build-manifest.json,final-variants-build-manifest.json} result/
cp -f "$OUT"/{ega-best,restore,script-arith,script-table,script-table-ldi,script-table-ldi-lazy,combined,final}.sna result/
cp -f "$OUT"/vm-*.bin "$OUT"/renderer-*.bin result/ 2>/dev/null || true
cp -f "$OPT/vm-port"/{final_perf_patch.py,final_perf_build.py,final_generate_restore_script.py,final_perf_runner.mjs,run_final_perf_ci.sh} result/
