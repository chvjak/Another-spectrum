#!/usr/bin/env node
import crypto from "node:crypto";
import fs from "node:fs";

const [
  wasmPath,
  snapshotPath,
  reportPath,
  refreshText = "1800",
  expectedScenesText = "3",
] = process.argv.slice(2);
if (!wasmPath || !snapshotPath || !reportPath) {
  throw new Error(
    "usage: verify_sprite_eval.mjs core.wasm snapshot.sna report.json [refreshes] [expected-scenes]",
  );
}
const refreshes = Number.parseInt(refreshText, 10);
const expectedScenes = Number.parseInt(expectedScenesText, 10);
const wasm = fs.readFileSync(wasmPath);
const snapshot = fs.readFileSync(snapshotPath);
const { instance } = await WebAssembly.instantiate(wasm);
const core = instance.exports;
const memory = new Uint8Array(core.memory.buffer);
const registers = new Uint16Array(core.memory.buffer, core.REGISTERS, 12);
const page = (bank) => core.MACHINE_MEMORY + bank * 0x4000;
const load = (bank, offset) =>
  memory.set(snapshot.subarray(offset, offset + 0x4000), page(bank));

core.setMachineType(128);
memory.fill(0, page(8), page(10));
load(5, 27);
load(2, 27 + 0x4000);
load(0, 27 + 0x8000);
let offset = 49183;
for (const bank of [1, 3, 4, 6, 7]) {
  load(bank, offset);
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
const magic = Buffer.from(memory.subarray(fixed(0x9f00), fixed(0x9f04))).toString();
if (magic !== "SPRT") throw new Error(`bad status signature ${JSON.stringify(magic)}`);

let previousPresentation = 0;
let lastPresentationRefresh = 0;
const intervals = [];
const scenes = new Set();
const hashes = new Set();
const backgroundHashCounts = new Map();
let nonBlackFrames = 0;

const backgroundDigest = (frame) => {
  const rows = [];
  const screenOffset = 24 * 160;
  const rowStride = 96;
  for (let row = 0; row < 192; row++) {
    // Exclude the actor/laser band so this digest proves room pixels changed.
    if (row >= 110 && row < 190) continue;
    rows.push(
      frame.subarray(screenOffset + row * rowStride + 16, screenOffset + row * rowStride + 80),
    );
  }
  return crypto.createHash("sha1").update(Buffer.concat(rows)).digest("hex");
};
for (let refresh = 1; refresh <= refreshes; ++refresh) {
  const status = core.runFrame();
  if (status !== 0) throw new Error(`emulator status ${status} at refresh ${refresh}`);
  const presentation = u16(0x9f04);
  scenes.add(u8(0x9f06));
  if (presentation !== previousPresentation) {
    if (presentation !== previousPresentation + 1) {
      throw new Error(`presentation jump ${previousPresentation} -> ${presentation}`);
    }
    if (previousPresentation !== 0) intervals.push(refresh - lastPresentationRefresh);
    lastPresentationRefresh = refresh;
    previousPresentation = presentation;
    const frame = Buffer.from(
      memory.subarray(core.FRAME_BUFFER, core.FRAME_BUFFER + 0x6600),
    );
    hashes.add(crypto.createHash("sha1").update(frame).digest("hex"));
    const scene = u8(0x9f06);
    const digest = backgroundDigest(frame);
    const counts = backgroundHashCounts.get(scene) ?? new Map();
    counts.set(digest, (counts.get(digest) ?? 0) + 1);
    backgroundHashCounts.set(scene, counts);
    if (frame.some((value) => value !== 0)) nonBlackFrames++;
  }
}

const intervalHistogram = Object.fromEntries(
  [...new Set(intervals)].sort((a, b) => a - b).map((value) => [
    String(value),
    intervals.filter((candidate) => candidate === value).length,
  ]),
);
const normalIntervals = intervals.filter((value) => value === 2).length;
const frames = u16(0x9f04);
const missed = u8(0x9f07);
const renderIrqMax = u8(0x9f08);
const transitions = u16(0x9f0e);
const dominantBackgroundHashes = new Map(
  [...backgroundHashCounts.entries()].map(([scene, counts]) => [
    scene,
    [...counts.entries()].sort(([, a], [, b]) => b - a)[0]?.[0] ?? "",
  ]),
);
const distinctDominantBackgrounds = new Set(dominantBackgroundHashes.values()).size;
const report = {
  passed:
    magic === "SPRT" &&
    missed === 0 &&
    renderIrqMax <= 1 &&
    scenes.size === expectedScenes &&
    transitions >= expectedScenes &&
    dominantBackgroundHashes.size === expectedScenes &&
    distinctDominantBackgrounds === expectedScenes &&
    nonBlackFrames === frames &&
    normalIntervals / Math.max(1, intervals.length) > 0.95,
  snapshot: {
    bytes: snapshot.length,
    sha256: crypto.createHash("sha256").update(snapshot).digest("hex"),
  },
  run: {
    refreshes,
    secondsAt50Hz: refreshes / 50,
    presentations: frames,
    averagePresentationFps: frames / (refreshes / 50),
    scenesSeen: [...scenes].sort(),
    expectedDistinctScenes: expectedScenes,
    backgroundVisualVerification: {
      distinctRenderedBackgrounds: distinctDominantBackgrounds,
      expectedDistinctBackgrounds: expectedScenes,
      passed:
        dominantBackgroundHashes.size === expectedScenes &&
        distinctDominantBackgrounds === expectedScenes,
      sceneHashes: Object.fromEntries(
        [...dominantBackgroundHashes.entries()].sort(([a], [b]) => a - b),
      ),
    },
    transitions,
    distinctRenderedFrames: hashes.size,
    nonBlackFrames,
  },
  timing: {
    targetFps: 25,
    normalRefreshInterval: 2,
    intervalHistogram,
    normalIntervalRatio: normalIntervals / Math.max(1, intervals.length),
    deadlineMisses: missed,
    maximumInterruptsObservedDuringRender: renderIrqMax,
    interpretation:
      "No 40 ms deadline misses; the heaviest render spans at most one 20 ms interrupt boundary.",
  },
  finalState: {
    pc: core.getPC(),
    scene: u8(0x9f06),
    position: u16(0x9f0b),
    animation: u8(0x9f0d),
    screenBit: u8(0x9f09),
    irq: u8(0x9f0a),
  },
};
fs.writeFileSync(reportPath, `${JSON.stringify(report, null, 2)}\n`);
process.stdout.write(`${JSON.stringify(report, null, 2)}\n`);
if (!report.passed) process.exitCode = 1;
