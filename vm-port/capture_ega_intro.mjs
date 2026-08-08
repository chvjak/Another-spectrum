#!/usr/bin/env node
import fs from 'node:fs';

const [wasmPath, snaPath, mode = 'actual'] = process.argv.slice(2);
if (!wasmPath || !snaPath || !['actual', 'uniform-target'].includes(mode)) {
  throw new Error('usage: node capture_ega_intro.mjs core.wasm snapshot.sna [actual|uniform-target]');
}
const wasm = fs.readFileSync(wasmPath);
const sna = fs.readFileSync(snaPath);
const { instance } = await WebAssembly.instantiate(wasm);
const core = instance.exports;
const memory = new Uint8Array(core.memory.buffer);
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
function spectrumOffset(y, xb) {
  return ((y & 0xC0) << 5) | ((y & 7) << 8) | ((y & 0x38) << 2) | xb;
}
function rgbScreen(bank) {
  const screen = memory.subarray(pageAddress(bank), pageAddress(bank) + 6912);
  const output = Buffer.alloc(320 * 240 * 3, 0);
  for (let y = 0; y < 192; y++) {
    for (let xb = 0; xb < 32; xb++) {
      const bits = screen[spectrumOffset(y, xb)];
      const attribute = screen[6144 + (y >> 3) * 32 + xb];
      const bright = (attribute >> 6) & 1;
      const ink = (attribute & 7) + bright * 8;
      const paper = ((attribute >> 3) & 7) + bright * 8;
      for (let bit = 0; bit < 8; bit++) {
        const color = palette[bits & (0x80 >> bit) ? ink : paper];
        const x = 32 + xb * 8 + bit;
        const yy = 24 + y;
        const destination = (yy * 320 + x) * 3;
        output[destination] = color[0]; output[destination + 1] = color[1]; output[destination + 2] = color[2];
      }
    }
  }
  return output;
}
function displayedRgb() { return rgbScreen((u8(0x930B) & 8) ? 7 : 5); }

if (mode === 'actual') {
  process.stdout.write(displayedRgb());
  let hostFrames = 0;
  while (u8(0x9307) === 0 && hostFrames < 300000) {
    const status = core.runFrame();
    if (status !== 0) throw new Error(`core status ${status}`);
    hostFrames++;
    if ((hostFrames & 1) === 0) process.stdout.write(displayedRgb());
  }
  process.stderr.write(`actual runtime capture: ${hostFrames} Spectrum refreshes\n`);
} else {
  const presentations = [displayedRgb()];
  let last = 0;
  let hostFrames = 0;
  while (u8(0x9307) === 0 && hostFrames < 300000) {
    const status = core.runFrame();
    if (status !== 0) throw new Error(`core status ${status}`);
    hostFrames++;
    const count = u16(0x9308);
    if (count !== last) {
      presentations.push(displayedRgb());
      last = count;
    }
  }
  const outputFrames = Math.round(164.52 * 25);
  for (let i = 0; i < outputFrames; i++) {
    const index = Math.min(presentations.length - 1, Math.floor(i * presentations.length / outputFrames));
    process.stdout.write(presentations[index]);
  }
  process.stderr.write(`uniform target preview: ${presentations.length} presentations -> ${outputFrames} frames\n`);
}
