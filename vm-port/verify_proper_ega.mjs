#!/usr/bin/env node
import crypto from 'node:crypto';
import fs from 'node:fs';

const [wasmPath, candidatePath, referencePath, reportPath] = process.argv.slice(2);
if (!reportPath) throw new Error('usage: verify_proper_ega.mjs core.wasm candidate.sna reference.sna report.json');
const wasm = fs.readFileSync(wasmPath);

async function load(snapshotPath) {
  const sna = fs.readFileSync(snapshotPath);
  const { instance } = await WebAssembly.instantiate(wasm);
  const core = instance.exports;
  const memory = new Uint8Array(core.memory.buffer);
  const regs = new Uint16Array(core.memory.buffer, core.REGISTERS, 12);
  const page = bank => core.MACHINE_MEMORY + bank * 0x4000;
  const copy = (bank, offset) => memory.set(sna.subarray(offset, offset + 0x4000), page(bank));
  core.setMachineType(128);
  memory.fill(0, page(8), page(10));
  copy(5, 27); copy(2, 27 + 0x4000); copy(0, 27 + 0x8000);
  let offset = 49183;
  for (const bank of [1, 3, 4, 6, 7]) { copy(bank, offset); offset += 0x4000; }
  regs.fill(0); regs[10] = 0xBFF0;
  core.setPC(0x8000); core.setIFF1(0); core.setIFF2(0); core.setIM(1); core.setHalted(false);
  core.writePort(0x00FE, 0); core.writePort(0x7FFD, 0); core.setTStates(0);
  const fixed = address => page(2) + address - 0x8000;
  const u8 = address => memory[fixed(address)];
  const u16 = address => u8(address) | (u8(address + 1) << 8);
  return { core, memory, page, u8, u16 };
}

async function capture(snapshotPath) {
  const machine = await load(snapshotPath);
  const frames = [];
  let refreshes = 0;
  let presentation = 0;
  while (machine.u8(0x9307) === 0 && refreshes < 100000) {
    const status = machine.core.runFrame();
    if (status !== 0) throw new Error(`core status ${status}`);
    refreshes++;
    const next = machine.u16(0x9308);
    if (next === presentation) continue;
    if (next !== presentation + 1) throw new Error(`presentation jump ${presentation} -> ${next}`);
    presentation = next;
    const presentedBank = machine.u8(0x9332) ? 7 : 5;
    frames.push(Buffer.from(machine.memory.subarray(machine.page(presentedBank), machine.page(presentedBank) + 6912)));
  }
  return {
    refreshes,
    done: machine.u8(0x9307),
    vmTick: machine.u16(0x9300),
    instructionCount: machine.u16(0x9302),
    traceHash: machine.u16(0x9304),
    frames,
  };
}

const [candidate, reference] = await Promise.all([capture(candidatePath), capture(referencePath)]);
if (candidate.frames.length !== reference.frames.length) throw new Error('presentation count mismatch');
const hashes = new Set();
let nonBlackPresentations = 0;
let mismatchBytes = 0;
let worstMismatchBytes = 0;
let exactPresentations = 0;
for (let i = 0; i < candidate.frames.length; i++) {
  const frame = candidate.frames[i];
  hashes.add(crypto.createHash('sha256').update(frame).digest('hex'));
  if (frame.some(value => value !== 0)) nonBlackPresentations++;
  let mismatch = 0;
  for (let j = 0; j < frame.length; j++) if (frame[j] !== reference.frames[i][j]) mismatch++;
  mismatchBytes += mismatch;
  worstMismatchBytes = Math.max(worstMismatchBytes, mismatch);
  if (mismatch === 0) exactPresentations++;
}
const report = {
  passed: candidate.done === 1 && candidate.frames.length === 298 && nonBlackPresentations > 0,
  candidate: {
    refreshes: candidate.refreshes,
    secondsAt50Hz: candidate.refreshes / 50,
    presentations: candidate.frames.length,
    distinctScreenHashes: hashes.size,
    nonBlackPresentations,
    vmTick: candidate.vmTick,
    instructionCount: candidate.instructionCount,
    traceHash: candidate.traceHash,
  },
  reference: { refreshes: reference.refreshes, secondsAt50Hz: reference.refreshes / 50 },
  comparison: {
    exactPresentations,
    averageMismatchBytes: mismatchBytes / candidate.frames.length,
    worstMismatchBytes,
    bytesPerScreen: 6912,
  },
};
fs.writeFileSync(reportPath, JSON.stringify(report, null, 2) + '\n');
console.log(JSON.stringify(report, null, 2));
if (!report.passed) process.exitCode = 1;
