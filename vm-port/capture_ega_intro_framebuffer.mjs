#!/usr/bin/env node
import fs from 'node:fs';
import { once } from 'node:events';

const [wasmPath, snaPath, mode = 'actual'] = process.argv.slice(2);
if (!wasmPath || !snaPath || !['actual', 'uniform-target'].includes(mode)) {
  throw new Error('usage: node capture_ega_intro_framebuffer.mjs core.wasm snapshot.sna [actual|uniform-target]');
}
const wasm = fs.readFileSync(wasmPath);
const sna = fs.readFileSync(snaPath);
const { instance } = await WebAssembly.instantiate(wasm);
const core = instance.exports;
let memory = new Uint8Array(core.memory.buffer);
const regs = new Uint16Array(core.memory.buffer, core.REGISTERS, 12);
const pageAddress = bank => core.MACHINE_MEMORY + bank * 0x4000;
const loadPage = (bank, sourceOffset) => memory.set(sna.subarray(sourceOffset, sourceOffset + 0x4000), pageAddress(bank));
core.setMachineType(128);
memory.fill(0, pageAddress(8), pageAddress(10));
loadPage(5, 27); loadPage(2, 27 + 0x4000); loadPage(0, 27 + 0x8000);
let sourceOffset = 49183;
for (const bank of [1, 3, 4, 6, 7]) { loadPage(bank, sourceOffset); sourceOffset += 0x4000; }
regs.fill(0); regs[10] = 0xBFF0;
core.setPC(0x8000); core.setIFF1(0); core.setIFF2(0); core.setIM(1); core.setHalted(false);
core.writePort(0x00FE, 0); core.writePort(0x7FFD, 0); core.setTStates(0);
const fixed = address => pageAddress(2) + address - 0x8000;
const u8 = address => memory[fixed(address)];
const u16 = address => u8(address) | (u8(address + 1) << 8);

const palette = [
  [0,0,0],[32,48,192],[192,64,16],[192,64,192],[64,176,16],[80,192,176],[224,192,16],[192,192,192],
  [0,0,0],[48,64,255],[255,64,48],[255,112,240],[80,224,16],[80,224,255],[255,232,80],[255,255,255],
];

// JSSpeccy's FRAME_BUFFER is the authoritative displayed 320x240 Spectrum
// image: 24 border rows, then 192 rows of border + 32 bitmap/attribute pairs,
// then 24 border rows. Using it avoids guessing which physical screen bank is
// currently selected by port 0x7FFD.
function rgbFrame() {
  memory = new Uint8Array(core.memory.buffer);
  const frame = memory.subarray(core.FRAME_BUFFER, core.FRAME_BUFFER + 0x6600);
  const out = Buffer.allocUnsafe(320 * 240 * 3);
  let input = 0;
  let output = 0;
  const pixel = index => {
    const color = palette[index & 15];
    out[output++] = color[0]; out[output++] = color[1]; out[output++] = color[2];
  };
  for (let y = 0; y < 24; y++) {
    for (let x = 0; x < 160; x++) { const c = frame[input++]; pixel(c); pixel(c); }
  }
  for (let y = 0; y < 192; y++) {
    for (let x = 0; x < 16; x++) { const c = frame[input++]; pixel(c); pixel(c); }
    for (let x = 0; x < 32; x++) {
      let bits = frame[input++];
      const attribute = frame[input++];
      const ink = ((attribute & 0x40) >> 3) | (attribute & 7);
      const paper = (attribute & 0x78) >> 3;
      for (let bit = 0; bit < 8; bit++) {
        pixel(bits & 0x80 ? ink : paper);
        bits = (bits << 1) & 0xFF;
      }
    }
    for (let x = 0; x < 16; x++) { const c = frame[input++]; pixel(c); pixel(c); }
  }
  for (let y = 0; y < 24; y++) {
    for (let x = 0; x < 160; x++) { const c = frame[input++]; pixel(c); pixel(c); }
  }
  return out;
}

async function writeFrame(frame) {
  if (!process.stdout.write(frame)) await once(process.stdout, 'drain');
}

if (mode === 'actual') {
  let hostFrames = 0;
  while (u8(0x9307) === 0 && hostFrames < 300000) {
    const status = core.runFrame();
    if (status !== 0) throw new Error(`core status ${status}`);
    hostFrames++;
    if ((hostFrames & 1) === 0) await writeFrame(rgbFrame());
  }
  process.stderr.write(`actual runtime capture: ${hostFrames} Spectrum refreshes\n`);
} else {
  const presentations = [];
  let last = 0;
  let hostFrames = 0;
  while (u8(0x9307) === 0 && hostFrames < 300000) {
    const status = core.runFrame();
    if (status !== 0) throw new Error(`core status ${status}`);
    hostFrames++;
    const count = u16(0x9308);
    if (count !== last) {
      presentations.push(rgbFrame());
      last = count;
    }
  }
  if (presentations.length !== 298) throw new Error(`captured ${presentations.length} presentations`);
  const outputFrames = Math.round(164.52 * 25);
  for (let i = 0; i < outputFrames; i++) {
    const index = Math.min(presentations.length - 1, Math.floor(i * presentations.length / outputFrames));
    await writeFrame(presentations[index]);
  }
  process.stderr.write(`uniform target preview: ${presentations.length} presentations -> ${outputFrames} frames\n`);
}
