#!/usr/bin/env node
import crypto from 'node:crypto';
import fs from 'node:fs';
import path from 'node:path';

const [wasmPath, buildDir] = process.argv.slice(2);
if (!wasmPath || !buildDir) {
  throw new Error('usage: node run_ega_profile.mjs core.wasm build-dir');
}
const wasm = fs.readFileSync(wasmPath);
const labels = ['current', 'restore', 'stack', 'both'];

function setupCore(sna) {
  return WebAssembly.instantiate(wasm).then(({ instance }) => {
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
    return { core, memory, pageAddress, u8, u16, b5u8, b5u16 };
  });
}

async function runVariant(label) {
  const sna = fs.readFileSync(path.join(buildDir, `${label}.sna`));
  const { core, memory, pageAddress, u8, u16, b5u8, b5u16 } = await setupCore(sna);
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
    seconds_at_50hz: hostFrames / 50,
    vm_tick: u16(0x9300),
    instruction_count: u16(0x9302),
    trace_hash: u16(0x9304),
    error_opcode: u8(0x9306),
    sampled_frames: u16(0x9308),
    hashed_presentations: hashedPresentations,
    screen_sequence_sha256: screenHash.digest('hex'),
    decoded_primitives: b5u16(0x7283),
    renderer_error: b5u8(0x7282),
    renderer_error_root: b5u16(0x72A2),
    renderer_error_shape: b5u16(0x729D),
    renderer_error_code: b5u8(0x729F),
  };
}

const popcount = new Uint8Array(256);
for (let i = 1; i < 256; i++) popcount[i] = popcount[i >> 1] + (i & 1);
const delta16 = (current, previous) => (current - previous + 0x10000) & 0xFFFF;

async function runProfile() {
  const sna = fs.readFileSync(path.join(buildDir, 'profile.sna'));
  const { core, memory, pageAddress, u8, u16, b5u8, b5u16 } = await setupCore(sna);
  let hostFrames = 0;
  let lastPresentation = 0;
  let lastHostFrame = 0;
  let previousLatch = [0, 0, 0, 0, 0];
  let previousBitmap = Buffer.alloc(6144);
  const frames = [];
  while (u8(0x9307) === 0 && hostFrames < 300000) {
    const status = core.runFrame();
    if (status !== 0) throw new Error(`profile: core status ${status}`);
    hostFrames++;
    const presentation = u16(0x9308);
    if (presentation === lastPresentation) continue;
    if (presentation !== lastPresentation + 1) {
      throw new Error(`profile presentation jump ${lastPresentation} -> ${presentation}`);
    }
    const latch = [];
    for (let i = 0; i < 5; i++) latch.push(u16(0x939C + i * 2));
    const values = latch.map((value, i) => delta16(value, previousLatch[i]));
    previousLatch = latch;
    const displayBank = (u8(0x930B) & 8) ? 7 : 5;
    const bitmap = Buffer.from(memory.subarray(pageAddress(displayBank), pageAddress(displayBank) + 6144));
    let changedBytes = 0;
    let changedPixels = 0;
    for (let i = 0; i < bitmap.length; i++) {
      const diff = bitmap[i] ^ previousBitmap[i];
      if (diff !== 0) changedBytes++;
      changedPixels += popcount[diff];
    }
    previousBitmap = bitmap;
    const [spanBytes, edgeBytes, interiorBytes, restoreBytes, fullBytes] = values;
    const totalBytes = spanBytes + restoreBytes + fullBytes;
    const refreshes = hostFrames - lastHostFrame;
    frames.push({
      presentation,
      vm_tick: u16(0x9300),
      host_refreshes: refreshes,
      host_seconds: refreshes / 50,
      span_bytes: spanBytes,
      masked_edge_bytes: edgeBytes,
      direct_interior_bytes: interiorBytes,
      restore_bytes: restoreBytes,
      full_page_bytes: fullBytes,
      total_bitmap_write_bytes: totalBytes,
      equivalent_written_pixels: totalBytes * 8,
      visible_changed_bitmap_bytes: changedBytes,
      visible_changed_pixels: changedPixels,
      write_bytes_per_refresh: refreshes ? totalBytes / refreshes : 0,
      display_bank: displayBank,
    });
    lastHostFrame = hostFrames;
    lastPresentation = presentation;
  }
  return {
    label: 'profile',
    done: u8(0x9307),
    host_frames: hostFrames,
    vm_tick: u16(0x9300),
    instruction_count: u16(0x9302),
    trace_hash: u16(0x9304),
    error_opcode: u8(0x9306),
    sampled_frames: u16(0x9308),
    decoded_primitives: b5u16(0x7283),
    renderer_error: b5u8(0x7282),
    frames,
  };
}

const runs = {};
for (const label of labels) runs[label] = await runVariant(label);
const reference = runs.current;
const valid = run => run.done === 1 && run.error_opcode === 0 && run.renderer_error === 0;
const sameTrace = run => run.vm_tick === reference.vm_tick &&
  run.instruction_count === reference.instruction_count && run.trace_hash === reference.trace_hash;
const sameVisual = run => run.hashed_presentations === reference.hashed_presentations &&
  run.screen_sequence_sha256 === reference.screen_sequence_sha256;
const comparisons = {};
for (const label of labels.slice(1)) {
  const run = runs[label];
  comparisons[label] = {
    passed: valid(run),
    trace_equal: sameTrace(run),
    primitives_equal: run.decoded_primitives === reference.decoded_primitives,
    sampled_screens_equal: sameVisual(run),
    speedup: reference.host_frames / run.host_frames,
    saved_percent: (1 - run.host_frames / reference.host_frames) * 100,
    saved_refreshes: reference.host_frames - run.host_frames,
  };
}
const validLabels = labels.filter(label => valid(runs[label]) && sameTrace(runs[label]) && sameVisual(runs[label]));
const winner = validLabels.reduce((best, label) => runs[label].host_frames < runs[best].host_frames ? label : best, validLabels[0]);
const matrix = {
  passed: valid(reference) && Object.values(comparisons).every(item =>
    item.passed && item.trace_equal && item.primitives_equal && item.sampled_screens_equal),
  reference: 'current',
  winner,
  runs,
  comparisons,
};
fs.writeFileSync(path.join(buildDir, 'ega-ab-result.json'), JSON.stringify(matrix, null, 2) + '\n');
fs.writeFileSync(path.join(buildDir, 'best-label.txt'), `${winner}\n`);

const profile = await runProfile();
fs.writeFileSync(path.join(buildDir, 'pixel-bandwidth-per-frame.json'), JSON.stringify(profile, null, 2) + '\n');
const columns = [
  'presentation','vm_tick','host_refreshes','host_seconds','span_bytes','masked_edge_bytes',
  'direct_interior_bytes','restore_bytes','full_page_bytes','total_bitmap_write_bytes',
  'equivalent_written_pixels','visible_changed_bitmap_bytes','visible_changed_pixels',
  'write_bytes_per_refresh','display_bank'
];
const csv = [columns.join(',')];
for (const frame of profile.frames) csv.push(columns.map(key => frame[key]).join(','));
fs.writeFileSync(path.join(buildDir, 'pixel-bandwidth-per-frame.csv'), csv.join('\n') + '\n');
console.log(JSON.stringify(matrix, null, 2));
console.log(JSON.stringify({
  profile_frames: profile.frames.length,
  profile_host_frames: profile.host_frames,
  total_bitmap_write_bytes: profile.frames.reduce((s, f) => s + f.total_bitmap_write_bytes, 0),
  total_visible_changed_pixels: profile.frames.reduce((s, f) => s + f.visible_changed_pixels, 0),
}, null, 2));
if (!matrix.passed || profile.done !== 1 || profile.renderer_error !== 0) process.exitCode = 1;
