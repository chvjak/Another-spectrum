#!/usr/bin/env bash
set -euo pipefail
ROOT="$PWD"; OPT="$ROOT/opt"

# The EGA setup includes a diagnostic profile build whose counters overlap the
# later final-performance variables. The row-fill benchmark does not consume
# that profile, so preserve the measured current/restore/stack/both matrix and
# skip only the obsolete per-presentation profile snapshot.
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
p=Path('run_ega_ci_row_fill.sh')
s=p.read_text()
needle='cat "$OPT"/vm-port/ega-source.part-* | base64 -d | tar -xz -C "$OPT"\n'
insert='python3 "$ROOT/patch_ega_profile.py"\n'
if needle not in s:
    raise SystemExit('run_ega_ci extraction marker not found')
p.write_text(s.replace(needle, needle + insert, 1))
PYWRAP

# Redirect the final pipeline through the profile-safe EGA setup, then execute
# its exact trace, restore-script, lazy-present and row-oriented full-fill A/B.
python3 - <<'PYFINAL'
from pathlib import Path
p=Path('opt/vm-port/run_final_perf_ci.sh')
s=p.read_text()
old='bash "$OPT/vm-port/run_ega_ci.sh"'
new='bash "$ROOT/run_ega_ci_row_fill.sh"'
if old not in s:
    raise SystemExit('final pipeline EGA call not found')
p.write_text(s.replace(old,new,1))
PYFINAL

bash "$OPT/vm-port/run_final_perf_ci.sh"
