#!/usr/bin/env node
import fs from 'node:fs';
import vm from 'node:vm';
import { once } from 'node:events';

const [dataPath, enginePath, mode = '--rgb'] = process.argv.slice(2);
if (!dataPath || !enginePath || !['--rgb', '--indexed', '--palette-ids', '--page3-snapshots'].includes(mode)) {
  throw new Error('usage: capture_original_colour_preview.mjs ootwdemo.js another.min.js [--rgb|--indexed|--palette-ids|--page3-snapshots]');
}
globalThis.atob = value => Buffer.from(value, 'base64').toString('binary');
globalThis.window = globalThis;
globalThis.document = {};
// stdout is a raw RGB stream.  The original engine logs resource loads with
// console.log(), so route those diagnostics away from the binary payload.
globalThis.console.log = (...values) => process.stderr.write(`${values.join(' ')}\n`);
vm.runInThisContext(fs.readFileSync(dataPath, 'utf8') + '\n' + fs.readFileSync(enginePath, 'utf8'), { filename: enginePath });

let currentPaletteId = 0;
const originalSetPalette444 = set_palette_444;
set_palette_444 = (offset, type) => {
  if (type === PALETTE_TYPE_AMIGA) currentPaletteId = offset >>> 5;
  return originalSetPalette444(offset, type);
};

let lastDisplayOffset = null;
update_screen = offset => { lastDisplayOffset = offset; };

async function writeRgbFrame(offset) {
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

async function writeIndexedFrame(offset) {
  // Visible logical colours, page-0 logical colours, then the active 16-colour
  // RGB palette.  This preserves the information needed to build stable
  // Spectrum attributes without reverse-engineering colours from RGB pixels.
  const out = Buffer.allocUnsafe(320 * 200 * 2 + 16 * 3);
  let output = 0;
  for (const pageOffset of [offset, 0]) {
    for (let y = 0; y < 200; y++) {
      const row = pageOffset + (y * SCALE) * SCREEN_W;
      for (let x = 0; x < 320; x++) out[output++] = buffer8[row + x * SCALE] & 15;
    }
  }
  const paletteBase = 16 * palette_type;
  for (let index = 0; index < 16; index++) {
    const value = palette32[paletteBase + index] >>> 0;
    out[output++] = value & 255;
    out[output++] = (value >>> 8) & 255;
    out[output++] = (value >>> 16) & 255;
  }
  if (!process.stdout.write(out)) await once(process.stdout, 'drain');
}

async function writePage0Snapshot() {
  const out = Buffer.allocUnsafe(320 * 200 + 16 * 3);
  let output = 0;
  for (let y = 0; y < 200; y++) {
    const row = (y * SCALE) * SCREEN_W;
    for (let x = 0; x < 320; x++) out[output++] = buffer8[row + x * SCALE] & 15;
  }
  const paletteBase = 16 * palette_type;
  for (let index = 0; index < 16; index++) {
    const value = palette32[paletteBase + index] >>> 0;
    out[output++] = value & 255;
    out[output++] = (value >>> 8) & 255;
    out[output++] = (value >>> 16) & 255;
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
  if (mode === '--page3-snapshots' && (tick === 1597 || tick === 1712)) {
    await writePage0Snapshot();
    saved++;
  } else if (mode !== '--page3-snapshots' && tick >= 8 && (tick - 8) % 10 === 0) {
    const offset = lastDisplayOffset ?? current_page1 * PAGE_SIZE;
    if (mode === '--palette-ids') {
      if (!process.stdout.write(Buffer.from([currentPaletteId & 255]))) await once(process.stdout, 'drain');
    } else if (mode === '--indexed') await writeIndexedFrame(offset);
    else await writeRgbFrame(offset);
    saved++;
  }
  if (next_part !== 0) break;
}
process.stderr.write(`original-colour sampled frames: ${saved}\n`);
const expected = mode === '--page3-snapshots' ? 2 : 298;
if (saved !== expected) throw new Error(`expected ${expected} frames, got ${saved}`);
