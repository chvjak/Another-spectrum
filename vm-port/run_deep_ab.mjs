#!/usr/bin/env node
import crypto from 'node:crypto';
import fs from 'node:fs';
import path from 'node:path';

const [wasmPath, buildDir] = process.argv.slice(2);
if (!wasmPath || !buildDir) {
  throw new Error('usage: node run_deep_ab.mjs core.wasm build-dir');
}
const wasm = fs.readFileSync(wasmPath);
const labels = ['current', 'child', 'template', 'both'];

async function run(label) {
  const sna = fs.readFileSync(path.join(buildDir, `${label}.sna`));
  const { instance } = await WebAssembly.instantiate(wasm);
  const core = instance.exports;
  const memory = new Uint8Array(core.memory.buffer);
  const regs = new Uint16Array(core.memory.buffer, core.REGISTERS, 12);
  const pageAddress = bank => core.MACHINE_MEMORY + bank * 0x4000;
  const loadPage = (bank, sourceOffset) => {
    memory.set(sna.subarray(sourceOffset, sourceOffset + 0x4000), pageAddress(bank));
  };

  core.setMachineType(128);
  memory.fill(0, pageAddress(8), pageAddress(10));
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

  const fixed = address => pageAddress(2) + address - 0x8000;
  const u8 = address => memory[fixed(address)];
  const u16 = address => u8(address) | (u8(address + 1) << 8);
  const b5u8 = address => memory[pageAddress(5) + address - 0x4000];
  const b5u16 = address => b5u8(address) | (b5u8(address + 1) << 8);

  const screenHash = crypto.createHash('sha256');
  let lastPresentation = 0;
  let hashedPresentations = 0;
  let hostFrames = 0;
  while (u8(0x9307) === 0 && hostFrames < 300000) {
    const status = core.runFrame();
    if (status !== 0) throw new Error(`${label}: core status ${status}`);
    hostFrames++;
    const frameCount = u16(0x9308);
    if (frameCount !== lastPresentation) {
      if (frameCount !== lastPresentation + 1) {
        throw new Error(`${label}: presentation jump ${lastPresentation} -> ${frameCount}`);
      }
      const index = Buffer.allocUnsafe(2);
      index.writeUInt16LE(frameCount);
      screenHash.update(index);
      screenHash.update(memory.subarray(pageAddress(5), pageAddress(5) + 6912));
      screenHash.update(memory.subarray(pageAddress(7), pageAddress(7) + 6912));
      lastPresentation = frameCount;
      hashedPresentations++;
    }
  }

  return {
    label,
    done: u8(0x9307),
    host_frames: hostFrames,
    vm_tick: u16(0x9300),
    instruction_count: u16(0x9302),
    trace_hash: u16(0x9304),
    error_opcode: u8(0x9306),
    sampled_frames: u16(0x9308),
    hashed_presentations: hashedPresentations,
    screen_sequence_sha256: screenHash.digest('hex'),
    decoded_primitives: b5u16(0x7283),
    renderer_error: b5u8(0x7282),
    renderer_error_root: b5u16(0x72a2),
    renderer_error_shape: b5u16(0x729d),
    renderer_error_code: b5u8(0x729f),
  };
}

const runs = {};
for (const label of labels) runs[label] = await run(label);
const reference = runs.current;
const valid = run => run.done === 1 && run.error_opcode === 0 && run.renderer_error === 0;
const traceEqual = run =>
  run.vm_tick === reference.vm_tick &&
  run.instruction_count === reference.instruction_count &&
  run.trace_hash === reference.trace_hash;
const primitiveEqual = run => run.decoded_primitives === reference.decoded_primitives;
const visualEqual = run =>
  run.hashed_presentations === reference.hashed_presentations &&
  run.screen_sequence_sha256 === reference.screen_sequence_sha256;

const comparisons = {};
for (const label of labels.slice(1)) {
  const run = runs[label];
  comparisons[label] = {
    passed: valid(run),
    trace_equal: traceEqual(run),
    primitives_equal: primitiveEqual(run),
    sampled_screens_equal: visualEqual(run),
    speedup: reference.host_frames / run.host_frames,
    saved_percent: (1 - run.host_frames / reference.host_frames) * 100,
    saved_refreshes: reference.host_frames - run.host_frames,
  };
}
const report = {
  passed: valid(reference) && Object.values(comparisons).every(
    item => item.passed && item.trace_equal && item.primitives_equal && item.sampled_screens_equal
  ),
  reference: 'current',
  runs,
  comparisons,
};
fs.writeFileSync(path.join(buildDir, 'deep-ab-result.json'), JSON.stringify(report, null, 2) + '\n');
console.log(JSON.stringify(report, null, 2));
if (!report.passed) process.exitCode = 1;
