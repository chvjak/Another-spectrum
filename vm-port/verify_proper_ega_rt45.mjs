#!/usr/bin/env node
import crypto from 'node:crypto';
import fs from 'node:fs';

const [wasmPath, candidatePath, referencePath, planPath, reportPath] = process.argv.slice(2);
if (!reportPath) throw new Error('usage: verify_proper_ega_rt45.mjs core.wasm candidate.sna reference.sna plan.json report.json');
const wasm = fs.readFileSync(wasmPath);
const plan = JSON.parse(fs.readFileSync(planPath, 'utf8'));

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
  return { core, memory, page, registers: regs, u8, u16 };
}

async function capture(snapshotPath, scheduled) {
  const machine = await load(snapshotPath);
  const frames = [];
  let refreshes = 0;
  let presentation = 0;
  const expectedX = Uint8Array.from({ length: 256 }, (_, index) => (index - Math.floor(index / 5)) & 0xff);
  while (machine.u8(0x9307) === 0 && refreshes < 100000) {
    const status = machine.core.runFrame();
    if (status !== 0) throw new Error(`core status ${status}`);
    refreshes++;
    if (scheduled && process.env.AW_FAIL_ON_COORDINATE_WRITE === "1") {
      const changed = [];
      for (let index = 0; index < expectedX.length; index++) {
        const actual = machine.memory[machine.page(5) + 0x2f00 + index];
        if (actual !== expectedX[index]) changed.push({ table: "x", index, expected: expectedX[index], actual });
      }
      if (changed.length) {
        throw new Error(
          `coordinate table overwritten; ` + JSON.stringify({
            refreshes,
            presentation,
            tick: machine.u16(0x9300),
            pc: machine.core.getPC(),
            sp: machine.registers[10],
            changed: changed.slice(0, 12),
          }),
        );
      }
    }
    const next = machine.u16(scheduled ? 0x93ea : 0x9308);
    if (next === presentation) continue;
    if (next !== presentation + 1) {
      const xTable = machine.memory.subarray(machine.page(5) + 0x2f00, machine.page(5) + 0x3000);
      const xTableMismatches = [...xTable].filter((value, index) => value !== ((index - Math.floor(index / 5)) & 0xff)).length;
      throw new Error(
        `presentation jump ${presentation} -> ${next}; ` +
        JSON.stringify({
          refreshes,
          pc: machine.core.getPC(),
          sp: machine.registers[10],
          tick: machine.u16(0x9300),
          done: machine.u8(0x9307),
          opcode: machine.u8(0x9311),
          rendererError: machine.memory[machine.page(5) + 0x3282],
          display: machine.u8(0x930b),
          eventRunPtr: machine.u16(0x9333),
          eventRunRemain: machine.u8(0x9335),
          deepStreamPtr: machine.u16(0x9338),
          rtDropPtr: machine.u16(0x93e6),
          xTableMismatches,
        }),
      );
    }
    presentation = next;
    const presentedBank = machine.u8(0x9332) ? 7 : 5;
    const bytes = Buffer.from(machine.memory.subarray(machine.page(presentedBank), machine.page(presentedBank) + 6912));
    frames.push({ slot: scheduled ? machine.u16(0x93ee) : presentation, bytes });
  }
  return { refreshes, done: machine.u8(0x9307), vmTick: machine.u16(0x9300),
    instructionCount: machine.u16(0x9302), traceHash: machine.u16(0x9304), frames };
}

const [candidate, reference] = await Promise.all([capture(candidatePath, true), capture(referencePath, false)]);
const hashes = new Set();
let nonBlackPresentations = 0;
let mismatchBytes = 0;
let worstMismatchBytes = 0;
let exactPresentations = 0;
let orderedSlots = true;
let plannedSlots = candidate.frames.length === plan.keep_slots.length;
for (let i = 0; i < candidate.frames.length; i++) {
  const { slot, bytes } = candidate.frames[i];
  if (i && slot <= candidate.frames[i - 1].slot) orderedSlots = false;
  if (slot !== plan.keep_slots[i]) plannedSlots = false;
  const expected = reference.frames[slot - 1]?.bytes;
  if (!expected) throw new Error(`invalid retained slot ${slot}`);
  hashes.add(crypto.createHash('sha256').update(bytes).digest('hex'));
  if (bytes.some(value => value !== 0)) nonBlackPresentations++;
  let mismatch = 0;
  for (let j = 0; j < bytes.length; j++) if (bytes[j] !== expected[j]) mismatch++;
  mismatchBytes += mismatch;
  worstMismatchBytes = Math.max(worstMismatchBytes, mismatch);
  if (mismatch === 0) exactPresentations++;
}
const report = {
  passed: candidate.done === 1 && candidate.frames.length === plan.keep_slots.length && nonBlackPresentations > 0 && orderedSlots && plannedSlots,
  candidate: { refreshes: candidate.refreshes, secondsAt50Hz: candidate.refreshes / 50,
    presentations: candidate.frames.length, distinctScreenHashes: hashes.size, nonBlackPresentations,
    vmTick: candidate.vmTick, instructionCount: candidate.instructionCount, traceHash: candidate.traceHash,
    firstRetainedSlot: candidate.frames[0]?.slot, lastRetainedSlot: candidate.frames.at(-1)?.slot },
  reference: { refreshes: reference.refreshes, secondsAt50Hz: reference.refreshes / 50,
    presentations: reference.frames.length },
  comparison: { exactPresentations, averageMismatchBytes: mismatchBytes / candidate.frames.length,
    worstMismatchBytes, bytesPerScreen: 6912, retainedSlotsOrdered: orderedSlots,
    retainedSlotsMatchPlan: plannedSlots },
};
fs.writeFileSync(reportPath, JSON.stringify(report, null, 2) + '\n');
console.log(JSON.stringify(report, null, 2));
if (!report.passed) process.exitCode = 1;
