#!/usr/bin/env node
import fs from 'node:fs';
import vm from 'node:vm';
import { once } from 'node:events';

const [dataPath, enginePath, schedulePath, paletteMode = 'fixed'] = process.argv.slice(2);
if (!dataPath || !enginePath || !schedulePath || !['fixed', 'quantized'].includes(paletteMode)) {
  throw new Error('usage: render_rt45_demo.mjs ootwdemo.js another.min.js cost-4p5.json fixed|quantized');
}

// stdout is raw video only. Keep the engine's diagnostics on stderr.
console.log = (...args) => process.stderr.write(`${args.join(' ')}\n`);
globalThis.atob = value => Buffer.from(value, 'base64').toString('binary');
globalThis.window = globalThis;
globalThis.document = {};
vm.runInThisContext(fs.readFileSync(dataPath, 'utf8') + '\n' + fs.readFileSync(enginePath, 'utf8'), { filename: enginePath });

if (SCREEN_W !== 640 || SCREEN_H !== 400 || SCALE !== 2 || PAGE_SIZE !== 256000) {
  throw new Error(`unexpected engine framebuffer ${SCREEN_W}x${SCREEN_H}, scale=${SCALE}, page=${PAGE_SIZE}`);
}

const schedule = JSON.parse(fs.readFileSync(schedulePath, 'utf8'));
const dropped = new Set(schedule.drop_slots);
if (schedule.keep_slots.length !== 268 || dropped.size !== 30) {
  throw new Error(`unexpected schedule: kept=${schedule.keep_slots.length}, dropped=${dropped.size}`);
}

// The palette used by the earlier Spectrum geometry preview.
const SPECTRUM = [
  [0, 0, 0], [32, 48, 192], [192, 64, 16], [192, 64, 192],
  [64, 176, 16], [80, 192, 176], [224, 192, 16], [192, 192, 192],
  [24, 24, 24], [48, 64, 255], [255, 64, 48], [255, 112, 240],
  [80, 224, 16], [80, 224, 255], [255, 232, 80], [255, 255, 255],
];

const distance = Array.from({ length: 16 }, () => new Int32Array(16));
for (let a = 0; a < 16; a++) {
  for (let b = 0; b < 16; b++) {
    const dr = SPECTRUM[a][0] - SPECTRUM[b][0];
    const dg = SPECTRUM[a][1] - SPECTRUM[b][1];
    const db = SPECTRUM[a][2] - SPECTRUM[b][2];
    distance[a][b] = dr * dr + dg * dg + db * db;
  }
}

const nearestInBrightness = Array.from({ length: 2 }, () => new Uint8Array(16));
for (let bright = 0; bright < 2; bright++) {
  const base = bright * 8;
  for (let source = 0; source < 16; source++) {
    let best = base;
    for (let candidate = base + 1; candidate < base + 8; candidate++) {
      if (distance[source][candidate] < distance[source][best]) best = candidate;
    }
    nearestInBrightness[bright][source] = best;
  }
}

let lastDisplayOffset = null;
update_screen = offset => { lastDisplayOffset = offset; };

function paletteMap() {
  const map = new Uint8Array(16);
  if (paletteMode === 'fixed') {
    for (let i = 0; i < 16; i++) map[i] = i;
    return map;
  }
  const paletteBase = 16 * palette_type;
  for (let i = 0; i < 16; i++) {
    const value = palette32[paletteBase + i] >>> 0;
    const r = value & 255;
    const g = (value >>> 8) & 255;
    const b = (value >>> 16) & 255;
    let best = 0;
    let bestDistance = Number.POSITIVE_INFINITY;
    for (let candidate = 0; candidate < 16; candidate++) {
      const dr = r - SPECTRUM[candidate][0];
      const dg = g - SPECTRUM[candidate][1];
      const db = b - SPECTRUM[candidate][2];
      const d = dr * dr + dg * dg + db * db;
      if (d < bestDistance) { bestDistance = d; best = candidate; }
    }
    map[i] = best;
  }
  return map;
}

// Convert the engine's authoritative expanded 640x400 page into a 256x192
// Spectrum bitmap. Then enforce one shared BRIGHT setting and two colours per
// 8x8 attribute cell. The result is placed inside a 320x240 Spectrum border.
function spectrumFrame(pageOffset) {
  const map = paletteMap();
  const logical = new Uint8Array(256 * 192);
  for (let y = 0; y < 192; y++) {
    const sy = Math.floor(y * 200 / 192);
    const sourceRow = pageOffset + sy * SCALE * SCREEN_W;
    const destinationRow = y * 256;
    for (let x = 0; x < 256; x++) {
      const sx = Math.floor(x * 320 / 256);
      logical[destinationRow + x] = map[buffer8[sourceRow + sx * SCALE] & 15];
    }
  }

  const out = Buffer.alloc(320 * 240 * 3, 0);
  const counts = new Uint16Array(16);
  const projected = new Uint16Array(16);
  for (let cellY = 0; cellY < 24; cellY++) {
    for (let cellX = 0; cellX < 32; cellX++) {
      counts.fill(0);
      for (let py = 0; py < 8; py++) {
        const row = (cellY * 8 + py) * 256 + cellX * 8;
        for (let px = 0; px < 8; px++) counts[logical[row + px]]++;
      }
      let brightVotes = 0;
      for (let c = 8; c < 16; c++) brightVotes += counts[c];
      const bright = brightVotes > 32 ? 1 : 0;
      projected.fill(0);
      for (let c = 0; c < 16; c++) projected[nearestInBrightness[bright][c]] += counts[c];
      const base = bright * 8;
      let paper = base;
      let ink = base;
      for (let c = base; c < base + 8; c++) {
        if (projected[c] > projected[paper]) paper = c;
      }
      for (let c = base; c < base + 8; c++) {
        if (c !== paper && (ink === paper || projected[c] > projected[ink])) ink = c;
      }
      if (ink === paper) ink = base + ((paper - base + 7) & 7);

      for (let py = 0; py < 8; py++) {
        const sourceRow = (cellY * 8 + py) * 256 + cellX * 8;
        const outputY = 24 + cellY * 8 + py;
        for (let px = 0; px < 8; px++) {
          const source = logical[sourceRow + px];
          const selected = distance[source][ink] <= distance[source][paper] ? ink : paper;
          const rgb = SPECTRUM[selected];
          const outputX = 32 + cellX * 8 + px;
          const p = (outputY * 320 + outputX) * 3;
          out[p] = rgb[0]; out[p + 1] = rgb[1]; out[p + 2] = rgb[2];
        }
      }
    }
  }
  return out;
}

async function writeFrame(frame) {
  if (!process.stdout.write(frame)) await once(process.stdout, 'drain');
}

reset();
restart(16001);
next_part = 0;
vars[0xf2] = 4000;
let sampled = 0;
let kept = 0;
let held = null;
for (let tick = 0; tick < 4000; tick++) {
  lastDisplayOffset = null;
  run_tasks();
  if (tick >= 8 && (tick - 8) % 10 === 0) {
    const slot = sampled + 1;
    const pageOffset = lastDisplayOffset ?? current_page1 * PAGE_SIZE;
    const current = spectrumFrame(pageOffset);
    if (!dropped.has(slot)) {
      held = current;
      kept++;
    }
    if (held === null) throw new Error(`slot ${slot} dropped before first retained frame`);
    await writeFrame(held);
    sampled++;
  }
  if (next_part !== 0) break;
}
process.stderr.write(`rendered ${sampled} timeline slots, ${kept} distinct retained frames, mode=${paletteMode}\n`);
if (sampled !== 298 || kept !== 268) throw new Error(`unexpected render counts ${sampled}/${kept}`);
