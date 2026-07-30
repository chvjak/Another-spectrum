#!/usr/bin/env node
import fs from 'node:fs';
import vm from 'node:vm';
import { once } from 'node:events';

const [dataPath, enginePath] = process.argv.slice(2);
if (!dataPath || !enginePath) throw new Error('usage: capture_original_colour_preview.mjs ootwdemo.js another.min.js');
globalThis.atob = value => Buffer.from(value, 'base64').toString('binary');
globalThis.window = globalThis;
globalThis.document = {};
// another.min.js logs resource loads through console.log. This program writes
// packed RGB24 on stdout, so even one text line corrupts all later frame
// boundaries and appears as horizontal wrapping/warping in the encoded video.
console.log = () => {};
vm.runInThisContext(fs.readFileSync(dataPath, 'utf8') + '\n' + fs.readFileSync(enginePath, 'utf8'), { filename: enginePath });

let lastDisplayOffset = null;
update_screen = offset => { lastDisplayOffset = offset; };

async function writeFrame(offset) {
  const out = Buffer.allocUnsafe(320 * 200 * 3);
  let output = 0;
  const paletteBase = 16 * palette_type;
  for (let y = 0; y < 200; y++) {
    const row = offset + (y * SCALE) * SCREEN_W;
    for (let x = 0; x < 320; x++) {
      const index = buffer8[row + x * SCALE] & 15;
      const value = palette32[paletteBase + index] >>> 0;
      out[output++] = value & 255;
      out[output++] = (value >>> 8) & 255;
      out[output++] = (value >>> 16) & 255;
    }
  }
  if (!process.stdout.write(out)) await once(process.stdout, 'drain');
}

reset();
restart(16001);
next_part = 0;
vars[0xf2] = 4000;
let saved = 0;
for (let tick = 0; tick < 4000; tick++) {
  lastDisplayOffset = null;
  run_tasks();
  if (tick >= 8 && (tick - 8) % 10 === 0) {
    const offset = lastDisplayOffset ?? current_page1 * PAGE_SIZE;
    await writeFrame(offset);
    saved++;
  }
  if (next_part !== 0) break;
}
process.stderr.write(`original-colour sampled frames: ${saved}\n`);
if (saved !== 298) throw new Error(`expected 298 frames, got ${saved}`);
