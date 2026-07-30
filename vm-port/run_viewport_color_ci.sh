#!/usr/bin/env bash
set -euo pipefail
ROOT="$PWD"
OPT="$ROOT/opt"
mkdir -p "$ROOT/game-data" "$ROOT/bench" "$ROOT/deep-data" "$ROOT/out-vp" "$ROOT/result-vp" "$OPT/vm-port/build-full"

cat "$OPT"/vm-port/ega-source.part-* | base64 -d | tar -xz -C "$OPT"
python3 - <<'PY'
from pathlib import Path
p=Path('opt/vm-port/ega_renderer_patch.py')
s=p.read_text()
for old,new in {
    'jr nz,ega_restore_not_full':'jp nz,ega_restore_not_full',
    'jr ega_restore_next_row':'jp ega_restore_next_row',
}.items():
    if old not in s: raise SystemExit(f'missing EGA jump {old}')
    s=s.replace(old,new)
p.write_text(s)
PY
python3 -m py_compile "$OPT/vm-port/viewport_color_build.py" "$OPT/vm-port/ega_renderer_patch.py"
node --check "$OPT/vm-port/run_viewport_color_matrix.mjs"

if [ ! -d "$ROOT/game-data/repo" ]; then
  git clone --depth 1 --branch gh-pages https://github.com/cyxx/another_js.git "$ROOT/game-data/repo"
fi
cp "$ROOT/game-data/repo/ootwdemo.js" "$ROOT/game-data/ootwdemo.js"
cp "$ROOT/game-data/repo/another.min.js" "$ROOT/game-data/another.min.js"

node "$OPT/vm-port/generate_optimizer_trace.mjs" \
  "$ROOT/game-data/ootwdemo.js" "$ROOT/game-data/another.min.js" \
  "$OPT/vm-port/build-full/optimizer-trace.log"
python3 "$OPT/vm-port/optimize_draws.py"
python3 - <<'PY'
from pathlib import Path
packed=Path('opt/vm-port/build-full/draw-event-keep-mask.bin').read_bytes()
count=9648
bits=[(packed[i>>3]>>(i&7))&1 for i in range(count)]
out=bytearray([bits[0]])
current=bits[0]; run=0
for bit in bits:
    if bit==current and run<255:
        run+=1; continue
    out.append(run)
    if bit==current: out.append(0)
    current=bit; run=1
out.append(run)
Path('bench/event-runs.bin').write_bytes(out)
PY
node "$OPT/vm-port/generate_deep_trace.mjs" \
  "$ROOT/game-data/ootwdemo.js" "$ROOT/game-data/another.min.js" "$ROOT/deep-data/deep-trace.log"
python3 "$OPT/vm-port/deep_optimize.py" \
  --trace "$ROOT/deep-data/deep-trace.log" \
  --event-mask "$OPT/vm-port/build-full/draw-event-keep-mask.bin" \
  --out "$ROOT/deep-data"

git -C "$OPT" show 86eb222f5a313e80fac2996f6edd11e697fcf563:vm-port/ci-minimal-full-ab.py.gz.b64 > "$ROOT/bench/minimal.b64"
python3 - <<'PY'
import base64,gzip,pathlib,re
text=pathlib.Path('bench/minimal.b64').read_text()
encoded=''.join(re.findall(r'[A-Za-z0-9+/=]',text))
pathlib.Path('bench/minimal_full_ab.py').write_bytes(gzip.decompress(base64.b64decode(encoded)))
PY
python3 "$OPT/vm-port/patch_ab_resources.py" "$ROOT/bench/minimal_full_ab.py"

if [ ! -x "$OPT/vendor-sjasmplus/sjasmplus" ]; then
  git clone --depth 1 --recurse-submodules --shallow-submodules https://github.com/z00m128/sjasmplus.git "$OPT/vendor-sjasmplus"
  make -C "$OPT/vendor-sjasmplus" -j2
fi
if [ ! -d "$OPT/vendor-jsspeccy3" ]; then
  git clone https://github.com/gasman/jsspeccy3.git "$OPT/vendor-jsspeccy3"
  git -C "$OPT/vendor-jsspeccy3" checkout cf886f39c2a72752a0bd49568fef398b141c11f2
  npm --prefix "$OPT/vendor-jsspeccy3" ci
  npm --prefix "$OPT/vendor-jsspeccy3" run build:core
  npm --prefix "$OPT/vendor-jsspeccy3" run build:wasm:release
fi

python3 "$OPT/vm-port/viewport_color_build.py" \
  --source-dir "$OPT/vm-port" \
  --helper "$ROOT/bench/minimal_full_ab.py" \
  --resource-js "$ROOT/game-data/ootwdemo.js" \
  --event-runs "$ROOT/bench/event-runs.bin" \
  --deep-data "$ROOT/deep-data" \
  --sjasmplus "$OPT/vendor-sjasmplus/sjasmplus" \
  --out "$ROOT/out-vp"

WASM="$OPT/vendor-jsspeccy3/dist/jsspeccy/jsspeccy-core.wasm"
node "$OPT/vm-port/run_viewport_color_matrix.mjs" "$WASM" "$ROOT/out-vp"
cp -f "$ROOT/out-vp"/viewport-color-result.json "$ROOT/out-vp"/viewport-color-build-manifest.json "$ROOT/result-vp/"
cp -f "$ROOT/out-vp"/*.sna "$ROOT/result-vp/"
cp -f "$ROOT/out-vp"/vm-*.bin "$ROOT/out-vp"/renderer-*.bin "$ROOT/result-vp/"
