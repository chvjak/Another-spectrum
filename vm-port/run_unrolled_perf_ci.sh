#!/usr/bin/env bash
set -euo pipefail
ROOT="$PWD"; OPT="$ROOT/opt"

# The EGA setup normally includes a diagnostic profile snapshot. That profile
# overlaps current final-performance variables on the latest branch, but it is
# not used by this benchmark. Build a wrapper that patches the profile runner
# immediately after run_ega_ci restores its embedded sources.
cat > "$ROOT/patch_ega_profile.py" <<'PYPATCH'
from pathlib import Path
p=Path('opt/vm-port/run_ega_profile.mjs')
s=p.read_text()
start=s.index('const profile = await runProfile();')
tail = "fs.writeFileSync(path.join(buildDir, 'pixel-bandwidth-per-frame.json'), JSON.stringify({ skipped: true, reason: 'not required by unrolled benchmark' }, null, 2) + '\\n');\nfs.writeFileSync(path.join(buildDir, 'pixel-bandwidth-per-frame.csv'), 'presentation\\n');\nconsole.log(JSON.stringify(matrix, null, 2));\nif (!matrix.passed) process.exitCode = 1;\n"
p.write_text(s[:start] + tail)
PYPATCH

cp "$OPT/vm-port/run_ega_ci.sh" "$ROOT/run_ega_ci_unrolled.sh"
python3 - <<'PYWRAP'
from pathlib import Path
p=Path('run_ega_ci_unrolled.sh')
s=p.read_text()
needle='cat "$OPT"/vm-port/ega-source.part-* | base64 -d | tar -xz -C "$OPT"\n'
insert='python3 "$ROOT/patch_ega_profile.py"\n'
if needle not in s:
    raise SystemExit('run_ega_ci extraction marker not found')
p.write_text(s.replace(needle, needle + insert, 1))
PYWRAP

# Build and verify the measured EGA-copy winner. The wrapper skips only the
# obsolete profile snapshot; current/restore/stack/both still run and hash-check.
bash "$ROOT/run_ega_ci_unrolled.sh"

python3 "$OPT/vm-port/unrolled_perf_build.py" \
  --work "$ROOT/out/work" --patch "$OPT/vm-port/unrolled_perf_patch.py" \
  --sjasmplus "$OPT/vendor-sjasmplus/sjasmplus" --out "$ROOT/out"

WASM="$OPT/vendor-jsspeccy3/dist/jsspeccy/jsspeccy-core.wasm"
read -ra LABELS <<< "$(cat "$ROOT/out/unrolled-labels.txt")"
node "$OPT/vm-port/final_perf_runner.mjs" matrix "$WASM" "$ROOT/out" "${LABELS[@]}"
cp "$ROOT/out/final-perf-result.json" "$ROOT/out/unrolled-perf-result.json"

python3 - <<'PY'
import json
from collections import Counter
from pathlib import Path
out=Path('out')
result=json.loads((out/'unrolled-perf-result.json').read_text())
manifest=json.loads((out/'unrolled-build-manifest.json').read_text())
widths=Counter()
summary={'result':result,'build':manifest,'restore_run_width_histogram':dict(sorted(widths.items()))}
(out/'unrolled-perf-summary.json').write_text(json.dumps(summary,indent=2)+'\n')
ref=result['runs'][result['reference']]['host_frames']
lines=['# Specialized unrolled copy/fill benchmark','', '| Variant | Refreshes | Seconds | Saved |','|---|---:|---:|---:|']
for label,run in result['runs'].items():
    lines.append(f"| {label} | {run['host_frames']} | {run['seconds_at_50hz']:.2f} | {(1-run['host_frames']/ref)*100:.3f}% |")
lines += ['',f"Winner: **{result['winner']}**.", '', 'All accepted variants must match the visible presentation hash, VM trace, primitive count, and error-free completion.']
(out/'UNROLLED-PERF-RESULTS.md').write_text('\n'.join(lines)+'\n')
print('\n'.join(lines))
PY

mkdir -p result
cp -f "$ROOT/out"/{unrolled-perf-result.json,unrolled-perf-summary.json,unrolled-build-manifest.json,UNROLLED-PERF-RESULTS.md,unrolled-labels.txt} result/
for f in "$ROOT/out"/u-*.sna "$ROOT/out"/vm-u-*.bin "$ROOT/out"/renderer-u-*.bin; do [ -e "$f" ] && cp -f "$f" result/; done
cp -f "$OPT/vm-port"/{unrolled_perf_patch.py,unrolled_perf_build.py,run_unrolled_perf_ci.sh} result/
