#!/usr/bin/env node
import fs from "node:fs";
import path from "node:path";

const [wasmPath, candidatePath, referencePath, outputDirectory] = process.argv.slice(2);
if (!outputDirectory) {
  throw new Error(
    "usage: analyze_visual_mismatch.mjs core.wasm candidate.sna reference.sna output-directory",
  );
}

const wasm = fs.readFileSync(wasmPath);

async function load(snapshotPath) {
  const snapshot = fs.readFileSync(snapshotPath);
  const { instance } = await WebAssembly.instantiate(wasm);
  const core = instance.exports;
  const memory = new Uint8Array(core.memory.buffer);
  const registers = new Uint16Array(core.memory.buffer, core.REGISTERS, 12);
  const page = (bank) => core.MACHINE_MEMORY + bank * 0x4000;
  const copy = (bank, offset) =>
    memory.set(snapshot.subarray(offset, offset + 0x4000), page(bank));

  core.setMachineType(128);
  memory.fill(0, page(8), page(10));
  copy(5, 27);
  copy(2, 27 + 0x4000);
  copy(0, 27 + 0x8000);
  let offset = 49183;
  for (const bank of [1, 3, 4, 6, 7]) {
    copy(bank, offset);
    offset += 0x4000;
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

  const fixed = (address) => page(2) + address - 0x8000;
  const u8 = (address) => memory[fixed(address)];
  const u16 = (address) => u8(address) | (u8(address + 1) << 8);
  return { core, memory, page, fixed, u8, u16 };
}

async function capture(snapshotPath) {
  const machine = await load(snapshotPath);
  const frames = [];
  const coordinateTables = [];
  let refreshes = 0;
  let presentation = 0;
  while (machine.u8(0x9307) === 0 && refreshes < 100000) {
    const status = machine.core.runFrame();
    if (status !== 0) throw new Error(`core status ${status}`);
    refreshes++;
    const next = machine.u16(0x9308);
    if (next === presentation) continue;
    if (next !== presentation + 1) {
      throw new Error(`presentation jump ${presentation} -> ${next}`);
    }
    presentation = next;
    const displayBank = machine.u8(0x9332) ? 7 : 5;
    frames.push(
      Buffer.from(
        machine.memory.subarray(
          machine.page(displayBank),
          machine.page(displayBank) + 6912,
        ),
      ),
    );
    coordinateTables.push(
      Buffer.from(
        machine.memory.subarray(machine.page(5) + 0x2f00, machine.page(5) + 0x3000),
      ),
    );
  }
  return { refreshes, frames, coordinateTables };
}

function spectrumOffset(y, byteX) {
  return ((y & 0xc0) << 5) | ((y & 7) << 8) | ((y & 0x38) << 2) | byteX;
}

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

function screenRgb(screen) {
  const rgb = Buffer.alloc(256 * 192 * 3);
  for (let y = 0; y < 192; y++) {
    for (let byteX = 0; byteX < 32; byteX++) {
      const bits = screen[spectrumOffset(y, byteX)];
      const attribute = screen[6144 + (y >> 3) * 32 + byteX];
      const bright = (attribute >> 6) & 1;
      const ink = (attribute & 7) + bright * 8;
      const paper = ((attribute >> 3) & 7) + bright * 8;
      for (let bit = 0; bit < 8; bit++) {
        const color = palette[bits & (0x80 >> bit) ? ink : paper];
        const destination = (y * 256 + byteX * 8 + bit) * 3;
        rgb[destination] = color[0];
        rgb[destination + 1] = color[1];
        rgb[destination + 2] = color[2];
      }
    }
  }
  return rgb;
}

function writePpm(filename, screen) {
  const header = Buffer.from("P6\n256 192\n255\n");
  fs.writeFileSync(filename, Buffer.concat([header, screenRgb(screen)]));
}

function writeDiffPpm(filename, candidate, reference) {
  const rgb = Buffer.alloc(256 * 192 * 3);
  for (let y = 0; y < 192; y++) {
    for (let byteX = 0; byteX < 32; byteX++) {
      const bitmapOffset = spectrumOffset(y, byteX);
      const attributeOffset = 6144 + (y >> 3) * 32 + byteX;
      const changed =
        candidate[bitmapOffset] !== reference[bitmapOffset] ||
        candidate[attributeOffset] !== reference[attributeOffset];
      for (let bit = 0; bit < 8; bit++) {
        const destination = (y * 256 + byteX * 8 + bit) * 3;
        rgb[destination] = changed ? 255 : 20;
        rgb[destination + 1] = changed ? 0 : 20;
        rgb[destination + 2] = changed ? 255 : 20;
      }
    }
  }
  const header = Buffer.from("P6\n256 192\n255\n");
  fs.writeFileSync(filename, Buffer.concat([header, rgb]));
}

const [candidate, reference] = await Promise.all([
  capture(candidatePath),
  capture(referencePath),
]);
if (candidate.frames.length !== reference.frames.length) {
  throw new Error(
    `presentation count mismatch ${candidate.frames.length} != ${reference.frames.length}`,
  );
}

const perFrame = candidate.frames.map((frame, index) => {
  const expected = reference.frames[index];
  let bitmapBytes = 0;
  let attributeBytes = 0;
  for (let offset = 0; offset < 6144; offset++) {
    if (frame[offset] !== expected[offset]) bitmapBytes++;
  }
  for (let offset = 6144; offset < 6912; offset++) {
    if (frame[offset] !== expected[offset]) attributeBytes++;
  }
  return {
    presentation: index + 1,
    bitmapBytes,
    attributeBytes,
    totalBytes: bitmapBytes + attributeBytes,
  };
});

const expectedCoordinateTables = Buffer.from([
  ...Array.from({ length: 256 }, (_, value) => (value - Math.floor(value / 5)) & 0xff),
]);
const coordinateTableMismatches = candidate.coordinateTables.map((table) => {
  let mismatches = 0;
  for (let offset = 0; offset < expectedCoordinateTables.length; offset++) {
    if (table[offset] !== expectedCoordinateTables[offset]) mismatches++;
  }
  return mismatches;
});

const ranked = [...perFrame].sort(
  (left, right) => right.totalBytes - left.totalBytes,
);
const firstMismatch = perFrame.find((frame) => frame.totalBytes > 0) ?? null;
const worst = ranked[0];
const report = {
  candidateRefreshes: candidate.refreshes,
  referenceRefreshes: reference.refreshes,
  presentations: perFrame.length,
  exactPresentations: perFrame.filter((frame) => frame.totalBytes === 0).length,
  firstMismatch,
  worst,
  averageBitmapMismatchBytes:
    perFrame.reduce((sum, frame) => sum + frame.bitmapBytes, 0) / perFrame.length,
  averageAttributeMismatchBytes:
    perFrame.reduce((sum, frame) => sum + frame.attributeBytes, 0) / perFrame.length,
  coordinateTables: {
    firstPresentationMismatches: coordinateTableMismatches[0] ?? null,
    maximumMismatches: Math.max(...coordinateTableMismatches),
    mismatchedPresentations: coordinateTableMismatches.filter((count) => count > 0).length,
  },
  worstPresentations: ranked.slice(0, 12),
  perFrame,
};

fs.mkdirSync(outputDirectory, { recursive: true });
fs.writeFileSync(
  path.join(outputDirectory, "mismatch.json"),
  `${JSON.stringify(report, null, 2)}\n`,
);
for (const item of [firstMismatch, worst]) {
  if (!item) continue;
  const prefix = item === firstMismatch ? "first" : "worst";
  const index = item.presentation - 1;
  writePpm(path.join(outputDirectory, `${prefix}-candidate.ppm`), candidate.frames[index]);
  writePpm(path.join(outputDirectory, `${prefix}-reference.ppm`), reference.frames[index]);
  writeDiffPpm(
    path.join(outputDirectory, `${prefix}-diff.ppm`),
    candidate.frames[index],
    reference.frames[index],
  );
}
console.log(JSON.stringify(report, null, 2));
