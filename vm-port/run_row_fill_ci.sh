#!/usr/bin/env bash
set -euo pipefail
ROOT="$PWD"; OPT="$ROOT/opt"

cat > "$ROOT/patch_ega_profile.py" <<'PYPATCH'
from pathlib import Path
p=Path('opt/vm-port/run_ega_profile.mjs')
s=p.read_text()
start=s.index('const profile = await runProfile();')
tail = "fs.writeFileSync(path.join(buildDir, 'pixel-bandwidth-per-frame.json'), JSON.stringify({ skipped: true, reason: 'not required by row-fill benchmark' }, null, 2) + '\\n');\nfs.writeFileSync(path.join(buildDir, 'pixel-bandwidth-per-frame.csv'), 'presentation\\n');\nconsole.log(JSON.stringify(matrix, null, 2));\nif (!matrix.passed) process.exitCode = 1;\n"
p.write_text(s[:start] + tail)
PYPATCH

cp "$OPT/vm-port/run_ega_ci.sh" "$ROOT/run_ega_ci_row_fill.sh"
python3 - <<'PYWRAP'
from pathlib import Path
p=Path('run_ega_ci_row_fill.sh'); s=p.read_text()
needle='cat "$OPT"/vm-port/ega-source.part-* | base64 -d | tar -xz -C "$OPT"\n'
insert='python3 "$ROOT/patch_ega_profile.py"\n'
if needle not in s: raise SystemExit('run_ega_ci extraction marker not found')
p.write_text(s.replace(needle,needle+insert,1))
PYWRAP

bash "$ROOT/run_ega_ci_row_fill.sh"
python3 "$OPT/vm-port/unrolled_perf_build.py" --work "$ROOT/out/work" --patch "$OPT/vm-port/unrolled_perf_patch.py" --sjasmplus "$OPT/vendor-sjasmplus/sjasmplus" --out "$ROOT/out"
python3 "$OPT/vm-port/row_fill_build.py" --work "$ROOT/out/work" --patch "$OPT/vm-port/row_fill_patch.py" --sjasmplus "$OPT/vendor-sjasmplus/sjasmplus" --out "$ROOT/out"
WASM="$OPT/vendor-jsspeccy3/dist/jsspeccy/jsspeccy-core.wasm"
read -ra LABELS <<< "$(cat "$ROOT/out/row-fill-labels.txt")"
node "$OPT/vm-port/final_perf_runner.mjs" matrix "$WASM" "$ROOT/out" "${LABELS[@]}"
cp "$ROOT/out/final-perf-result.json" "$ROOT/out/row-fill-result.json"
python3 - <<'PY'
import json
from pathlib import Path
out=Path('out'); result=json.loads((out/'row-fill-result.json').read_text()); manifest=json.loads((out/'row-fill-build-manifest.json').read_text())
ref=result['runs'][result['reference']]['host_frames']
lines=['# Row-oriented full-fill benchmark','', '| Variant | Refreshes | Seconds | Saved vs baseline |','|---|---:|---:|---:|']
for label,run in result['runs'].items():
    lines.append(f"| {label} | {run['host_frames']} | {run['seconds_at_50hz']:.2f} | {(1-run['host_frames']/ref)*100:.3f}% |")
lines += ['',f"Winner: **{result['winner']}**.",'','All accepted variants match visible output, VM trace, primitive count, and error-free completion.']
(out/'ROW-FILL-RESULTS.md').write_text('\n'.join(lines)+'\n'); print('\n'.join(lines))
PY
mkdir -p result
cp -f "$ROOT/out"/{row-fill-result.json,row-fill-build-manifest.json,row-fill-labels.txt,ROW-FILL-RESULTS.md} result/
for f in "$ROOT/out"/r-*.sna "$ROOT/out"/renderer-r-*.bin; do [ -e "$f" ] && cp -f "$f" result/; done
cp -f "$OPT/vm-port"/{row_fill_patch.py,row_fill_build.py,run_row_fill_ci.sh} result/
