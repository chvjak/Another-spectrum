import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const here = path.dirname(fileURLToPath(import.meta.url));
const build = path.join(here, 'build-full');
const sna = fs.readFileSync(path.join(build, 'another-world-vm-full.sna'));
const wasm = fs.readFileSync(path.join(here, '..', 'jsspeccy-core.wasm'));
const rom0 = fs.readFileSync(path.join(here, '..', 'rom-128-0.bin'));
const rom1 = fs.readFileSync(path.join(here, '..', 'rom-128-1.bin'));
const { instance } = await WebAssembly.instantiate(wasm);
const core = instance.exports;
const memory = new Uint8Array(core.memory.buffer);
const regs = new Uint16Array(core.memory.buffer, core.REGISTERS, 12);
const pageAddress = bank => core.MACHINE_MEMORY + bank * 0x4000;
const loadPage = (bank, sourceOffset) =>
  memory.set(sna.subarray(sourceOffset, sourceOffset + 0x4000), pageAddress(bank));

core.setMachineType(128);
memory.set(rom0, pageAddress(8));
memory.set(rom1, pageAddress(9));
loadPage(5, 27);
loadPage(2, 27 + 0x4000);
loadPage(0, 27 + 0x8000);
let sourceOffset = 49183;
for (const bank of [1, 3, 4, 6, 7]) {
  loadPage(bank, sourceOffset);
  sourceOffset += 0x4000;
}
regs.fill(0);
regs[10] = 0xBFF0;
core.setPC(0x8000);
core.setIFF1(0);
core.setIFF2(0);
core.setIM(1);
core.setHalted(false);
core.writePort(0x00FE, 0);
core.writePort(0x7FFD, 0);
core.setTStates(0);

const palette = [
  [0, 0, 0], [32, 48, 192], [192, 64, 16], [192, 64, 192],
  [64, 176, 16], [80, 192, 176], [224, 192, 16], [192, 192, 192],
  [0, 0, 0], [48, 64, 255], [255, 64, 48], [255, 112, 240],
  [80, 224, 16], [80, 224, 255], [255, 232, 80], [255, 255, 255],
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
        output[destination] = color[0];
        output[destination + 1] = color[1];
        output[destination + 2] = color[2];
      }
    }
  }
  return output;
}

function emitTen(frame) {
  for (let i = 0; i < 10; i++) process.stdout.write(frame);
}

// Presentation zero is the initial black page; each subsequent sampled VM
// screen is repeated for ten 50 Hz output frames to restore the 5 fps timeline.
emitTen(rgbScreen(5));
let sampledFrames = 0;
let hostFrames = 0;
while (sampledFrames < 298 && hostFrames < 60000) {
  const status = core.runFrame();
  if (status !== 0) throw new Error(`emulator stopped with status ${status}`);
  hostFrames++;
  const fixed = pageAddress(2);
  const count = memory[fixed + 0x1308] | (memory[fixed + 0x1309] << 8);
  if (count === sampledFrames) continue;
  const bank = memory[fixed + 0x1332] === 0 ? 5 : 7;
  emitTen(rgbScreen(bank));
  sampledFrames = count;
}
if (sampledFrames !== 298) {
  throw new Error(`capture ended after ${sampledFrames} sampled frames`);
}
process.stderr.write(`captured 2990 frames from ${hostFrames} emulator frames\n`);
