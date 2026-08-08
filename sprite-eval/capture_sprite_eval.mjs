#!/usr/bin/env node
import fs from "node:fs";
import { once } from "node:events";

const [wasmPath, snapshotPath, refreshText = "900"] = process.argv.slice(2);
if (!wasmPath || !snapshotPath) {
  throw new Error(
    "usage: capture_sprite_eval.mjs core.wasm snapshot.sna [Spectrum-refreshes]",
  );
}
const refreshes = Number.parseInt(refreshText, 10);
const wasm = fs.readFileSync(wasmPath);
const snapshot = fs.readFileSync(snapshotPath);
const { instance } = await WebAssembly.instantiate(wasm);
const core = instance.exports;
let memory = new Uint8Array(core.memory.buffer);
const registers = new Uint16Array(core.memory.buffer, core.REGISTERS, 12);
const page = (bank) => core.MACHINE_MEMORY + bank * 0x4000;
const load = (bank, offset) =>
  memory.set(snapshot.subarray(offset, offset + 0x4000), page(bank));

core.setMachineType(128);
memory.fill(0, page(8), page(10));
load(5, 27);
load(2, 27 + 0x4000);
load(0, 27 + 0x8000);
let sourceOffset = 49183;
for (const bank of [1, 3, 4, 6, 7]) {
  load(bank, sourceOffset);
  sourceOffset += 0x4000;
}
registers.fill(0);
registers[10] = 0xbff0;
core.setPC(0x8000);
core.setIFF1(0);
core.setIFF2(0);
core.setIM(1);
core.setHalted(false);
core.writePort(0x00fe, 0);
core.writePort(0x7ffd, 0);
core.setTStates(0);

const palette = [
  [0, 0, 0],
  [32, 48, 192],
  [192, 64, 16],
  [192, 64, 192],
  [64, 176, 16],
  [80, 192, 176],
  [224, 192, 16],
  [192, 192, 192],
  [0, 0, 0],
  [48, 64, 255],
  [255, 64, 48],
  [255, 112, 240],
  [80, 224, 16],
  [80, 224, 255],
  [255, 232, 80],
  [255, 255, 255],
];

function rgbFrame() {
  memory = new Uint8Array(core.memory.buffer);
  const frame = memory.subarray(core.FRAME_BUFFER, core.FRAME_BUFFER + 0x6600);
  const output = Buffer.allocUnsafe(320 * 240 * 3);
  let input = 0;
  let cursor = 0;
  const pixel = (index) => {
    const color = palette[index & 15];
    output[cursor++] = color[0];
    output[cursor++] = color[1];
    output[cursor++] = color[2];
  };
  for (let y = 0; y < 24; ++y) {
    for (let x = 0; x < 160; ++x) {
      const color = frame[input++];
      pixel(color);
      pixel(color);
    }
  }
  for (let y = 0; y < 192; ++y) {
    for (let x = 0; x < 16; ++x) {
      const color = frame[input++];
      pixel(color);
      pixel(color);
    }
    for (let x = 0; x < 32; ++x) {
      let bits = frame[input++];
      const attribute = frame[input++];
      const ink = ((attribute & 0x40) >> 3) | (attribute & 7);
      const paper = (attribute & 0x78) >> 3;
      for (let bit = 0; bit < 8; ++bit) {
        pixel(bits & 0x80 ? ink : paper);
        bits = (bits << 1) & 0xff;
      }
    }
    for (let x = 0; x < 16; ++x) {
      const color = frame[input++];
      pixel(color);
      pixel(color);
    }
  }
  for (let y = 0; y < 24; ++y) {
    for (let x = 0; x < 160; ++x) {
      const color = frame[input++];
      pixel(color);
      pixel(color);
    }
  }
  return output;
}

let written = 0;
for (let refresh = 1; refresh <= refreshes; ++refresh) {
  const status = core.runFrame();
  if (status !== 0) throw new Error(`emulator status ${status} at refresh ${refresh}`);
  if ((refresh & 1) !== 0) continue;
  const frame = rgbFrame();
  if (!process.stdout.write(frame)) await once(process.stdout, "drain");
  written++;
}
const fixed = (address) => page(2) + address - 0x8000;
const u8 = (address) => memory[fixed(address)];
const u16 = (address) => u8(address) | (u8(address + 1) << 8);
process.stderr.write(
  `${JSON.stringify({
    refreshes,
    framesWritten: written,
    presentations: u16(0x9f04),
    transitions: u16(0x9f0e),
    deadlineMisses: u8(0x9f07),
    renderIrqMax: u8(0x9f08),
  })}\n`,
);
