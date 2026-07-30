#!/usr/bin/env node
import crypto from 'node:crypto';
import fs from 'node:fs';
import path from 'node:path';

const [wasmPath, buildDir] = process.argv.slice(2);
if (!wasmPath || !buildDir) throw new Error('usage: run_viewport_color_matrix.mjs core.wasm build-dir');
const wasm = fs.readFileSync(wasmPath);
const labels = ['full-current', 'full-colorcopy', '240x176', '224x176', '224x160'];

async function run(label) {
  const sna = fs.readFileSync(path.join(buildDir, `${label}.sna`));
  const { instance } = await WebAssembly.instantiate(wasm);
  const core = instance.exports;
  const memory = new Uint8Array(core.memory.buffer);
  const regs = new Uint16Array(core.memory.buffer, core.REGISTERS, 12);
  const pageAddress = bank => core.MACHINE_MEMORY + bank * 0x4000;
  const loadPage = (bank, offset) => memory.set(sna.subarray(offset, offset + 0x4000), pageAddress(bank));

  core.setMachineType(128);
  memory.fill(0, pageAddress(8), pageAddress(10));
  loadPage(5, 27);
  loadPage(2, 27 + 0x4000);
  loadPage(0, 27 + 0x8000);
  let offset = 49183;
  for (const bank of [1, 3, 4, 6, 7]) {
    loadPage(bank, offset);
    offset += 0x4000;
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
  const bank5u8 = address => memory[pageAddress(5) + address - 0x4000];
  const bank5u16 = address => bank5u8(address) | (bank5u8(address + 1) << 8);

  let hostFrames = 0;
  let lastPresentation = 0;
  let hashedPresentations = 0;
  const screenHash = crypto.createHash('sha256');
  const visibleHash = crypto.createHash('sha256');
  while (u8(0x9307) === 0 && hostFrames < 300000) {
    const status = core.runFrame();
    if (status !== 0) throw new Error(`${label}: core status ${status}`);
    hostFrames++;
    const count = u16(0x9308);
    if (count !== lastPresentation) {
      if (count !== lastPresentation + 1) throw new Error(`${label}: presentation jump ${lastPresentation} -> ${count}`);
      const index = Buffer.allocUnsafe(2);
      index.writeUInt16LE(count);
      screenHash.update(index);
      screenHash.update(memory.subarray(pageAddress(5), pageAddress(5) + 6912));
      screenHash.update(memory.subarray(pageAddress(7), pageAddress(7) + 6912));

      visibleHash.update(index);
      const displayedBank = (u8(0x930B) & 8) !== 0 ? 7 : 5;
      visibleHash.update(memory.subarray(pageAddress(displayedBank), pageAddress(displayedBank) + 6912));

      lastPresentation = count;
      hashedPresentations++;
    }
  }

  return {
    label,
    done: u8(0x9307),
    host_frames: hostFrames,
    seconds_at_50hz: hostFrames / 50,
    vm_tick: u16(0x9300),
    instruction_count: u16(0x9302),
    trace_hash: u16(0x9304),
    error_opcode: u8(0x9306),
    sampled_frames: u16(0x9308),
    hashed_presentations: hashedPresentations,
    screen_sequence_sha256: screenHash.digest('hex'),
    visible_screen_sequence_sha256: visibleHash.digest('hex'),
    decoded_primitives: bank5u16(0x7283),
    renderer_error: bank5u8(0x7282),
  };
}

const runs = {};
for (const label of labels) runs[label] = await run(label);
const reference = runs['full-current'];
const valid = run => run.done === 1 && run.error_opcode === 0 && run.renderer_error === 0;
const result = {
  passed: labels.every(label => {
    const run = runs[label];
    return valid(run) && run.vm_tick === reference.vm_tick &&
      run.instruction_count === reference.instruction_count &&
      run.trace_hash === reference.trace_hash &&
      run.decoded_primitives === reference.decoded_primitives;
  }),
  reference: 'full-current',
  runs,
  comparisons: {},
};
for (const label of labels.slice(1)) {
  const run = runs[label];
  result.comparisons[label] = {
    speedup: reference.host_frames / run.host_frames,
    saved_percent: (1 - run.host_frames / reference.host_frames) * 100,
    saved_refreshes: reference.host_frames - run.host_frames,
    trace_equal: run.trace_hash === reference.trace_hash,
    primitives_equal: run.decoded_primitives === reference.decoded_primitives,
    both_physical_screens_equal: label === 'full-colorcopy' ? run.screen_sequence_sha256 === reference.screen_sequence_sha256 : null,
    visible_screen_equal: label === 'full-colorcopy' ? run.visible_screen_sequence_sha256 === reference.visible_screen_sequence_sha256 : null,
    target_factor: run.host_frames / (164.52 * 50),
  };
}
result.winner = labels.reduce((best, label) => runs[best].host_frames < runs[label].host_frames ? best : label);
fs.writeFileSync(path.join(buildDir, 'viewport-color-result.json'), JSON.stringify(result, null, 2) + '\n');
console.log(JSON.stringify(result, null, 2));
if (!result.passed || result.comparisons['full-colorcopy'].visible_screen_equal !== true) process.exitCode = 1;
