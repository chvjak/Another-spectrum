#!/usr/bin/env bash
set -euo pipefail
trap 'cp -f out/work/vm-restore.asm result/ 2>/dev/null || true; cp -f out/work/renderer-restore.asm result/ 2>/dev/null || true' ERR

ROOT="$PWD"
OPT="$ROOT/opt"
mkdir -p "$ROOT/game-data" "$ROOT/bench" "$ROOT/deep-data" "$ROOT/out" "$ROOT/result" "$OPT/vm-port/build-full"

cat "$OPT"/vm-port/ega-source.part-* | base64 -d | tar -xz -C "$OPT"
python3 - <<'PY'
from pathlib import Path
p=Path('opt/vm-port/ega_renderer_patch.py')
s=p.read_text()
old='jr nz,ega_restore_not_full'
print({'long_jump_occurrences_before': s.count(old)})
if old not in s:
    raise SystemExit('expected long restore jump not found')
s=s.replace(old,'jp nz,ega_restore_not_full')
p.write_text(s)
print({'long_jump_occurrences_after': p.read_text().count(old)})
PY
python3 -m py_compile "$OPT/vm-port/ega_renderer_patch.py" "$OPT/vm-port/ega_build_variants.py"
node --check "$OPT/vm-port/run_ega_profile.mjs"
node --check "$OPT/vm-port/capture_ega_intro.mjs"
python3 -m pip install --user numpy pillow

git clone --depth 1 --branch gh-pages https://github.com/cyxx/another_js.git "$ROOT/game-data/repo"
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

git clone --depth 1 --recurse-submodules --shallow-submodules https://github.com/z00m128/sjasmplus.git "$OPT/vendor-sjasmplus"
make -C "$OPT/vendor-sjasmplus" -j2

git clone https://github.com/gasman/jsspeccy3.git "$OPT/vendor-jsspeccy3"
git -C "$OPT/vendor-jsspeccy3" checkout cf886f39c2a72752a0bd49568fef398b141c11f2
npm --prefix "$OPT/vendor-jsspeccy3" ci
npm --prefix "$OPT/vendor-jsspeccy3" run build:core
npm --prefix "$OPT/vendor-jsspeccy3" run build:wasm:release

python3 "$OPT/vm-port/ega_build_variants.py" \
  --source-dir "$OPT/vm-port" \
  --helper "$ROOT/bench/minimal_full_ab.py" \
  --resource-js "$ROOT/game-data/ootwdemo.js" \
  --event-runs "$ROOT/bench/event-runs.bin" \
  --deep-data "$ROOT/deep-data" \
  --sjasmplus "$OPT/vendor-sjasmplus/sjasmplus" \
  --out "$ROOT/out"

WASM="$OPT/vendor-jsspeccy3/dist/jsspeccy/jsspeccy-core.wasm"
node "$OPT/vm-port/run_ega_profile.mjs" "$WASM" "$ROOT/out"
BEST=$(tr -d '\n' < "$ROOT/out/best-label.txt")

node "$OPT/vm-port/capture_ega_intro.mjs" "$WASM" "$ROOT/out/$BEST.sna" actual | \
ffmpeg -y -hide_banner -loglevel warning -f rawvideo -pixel_format rgb24 -video_size 320x240 -framerate 25 -i - \
  -vf scale=960:720:flags=neighbor -c:v libx264 -preset fast -crf 18 -pix_fmt yuv420p \
  "$ROOT/out/another-world-ega-best-actual-runtime.mp4"
node "$OPT/vm-port/capture_ega_intro.mjs" "$WASM" "$ROOT/out/$BEST.sna" uniform-target | \
ffmpeg -y -hide_banner -loglevel warning -f rawvideo -pixel_format rgb24 -video_size 320x240 -framerate 25 -i - \
  -vf scale=960:720:flags=neighbor -c:v libx264 -preset fast -crf 18 -pix_fmt yuv420p \
  "$ROOT/out/another-world-ega-best-uniform-164.52s-preview.mp4"
ffmpeg -y -hide_banner -loglevel warning -i "$ROOT/out/another-world-ega-best-uniform-164.52s-preview.mp4" \
  -vf "fps=12/164.52,scale=320:240:flags=neighbor,tile=4x3" -frames:v 1 "$ROOT/out/intro-contact-sheet.png"

cp -f "$ROOT/out/ega-ab-result.json" "$ROOT/out/ega-build-manifest.json" "$ROOT/result/"
cp -f "$ROOT/out/pixel-bandwidth-per-frame.json" "$ROOT/out/pixel-bandwidth-per-frame.csv" "$ROOT/result/"
cp -f "$ROOT/out/best-label.txt" "$ROOT/result/"
cp -f "$ROOT/out"/*.mp4 "$ROOT/out/intro-contact-sheet.png" "$ROOT/result/"
cp -f "$ROOT/out"/{current,restore,stack,both,profile}.sna "$ROOT/result/"
cp -f "$OPT/vm-port"/{ega_renderer_patch.py,ega_build_variants.py,run_ega_profile.mjs,capture_ega_intro.mjs} "$ROOT/result/"
