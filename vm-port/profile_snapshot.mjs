#!/usr/bin/env node
/** Profile a complete live-VM SNA without modifying the emulated program. */
import crypto from 'node:crypto';
import fs from 'node:fs';
import path from 'node:path';

const [wasmPath, snapshotPath, outputPath, capturesDir] = process.argv.slice(2);
if (!outputPath) {
  throw new Error(
    'usage: profile_snapshot.mjs core.wasm snapshot.sna output.json [captures-dir]',
  );
}

const FRAME_TSTATES_128K = 70_908;
const SNA_BYTES = 131_103;
const BANK_BYTES = 0x4000;
const sna = fs.readFileSync(snapshotPath);
if (sna.length !== SNA_BYTES) throw new Error(`unexpected SNA size ${sna.length}`);
const wasm = fs.readFileSync(wasmPath);
const { instance } = await WebAssembly.instantiate(wasm);
const core = instance.exports;
const memory = new Uint8Array(core.memory.buffer);
const registers = new Uint16Array(core.memory.buffer, core.REGISTERS, 12);
const page = bank => core.MACHINE_MEMORY + bank * BANK_BYTES;
const load = (bank, offset) => memory.set(sna.subarray(offset, offset + BANK_BYTES), page(bank));

core.setMachineType(128);
memory.fill(0, page(8), page(10));
load(5, 27);
load(2, 27 + BANK_BYTES);
load(0, 27 + BANK_BYTES * 2);
let snaOffset = 49_183;
for (const bank of [1, 3, 4, 6, 7]) {
  load(bank, snaOffset);
  snaOffset += BANK_BYTES;
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

const fixed = address => page(2) + address - 0x8000;
const u8 = address => memory[fixed(address)];
const u16 = address => u8(address) | (u8(address + 1) << 8);
const bank5u8 = address => memory[page(5) + address - 0x4000];
const bank5u16 = address => bank5u8(address) | (bank5u8(address + 1) << 8);
const popcount = new Uint8Array(256);
for (let value = 1; value < 256; value++) popcount[value] = popcount[value >> 1] + (value & 1);
const delta16 = (current, previous) => (current - previous + 0x10000) & 0xffff;
const sha256 = bytes => crypto.createHash('sha256').update(bytes).digest('hex');
const percentile = (values, fraction) => {
  if (!values.length) return null;
  const ordered = [...values].sort((a, b) => a - b);
  return ordered[Math.ceil(fraction * ordered.length) - 1];
};

if (capturesDir) fs.mkdirSync(capturesDir, { recursive: true });
let refreshes = 0;
let lastPresentation = 0;
let lastPresentationRefresh = 0;
let lastPresentationTstates = 0;
let previousPrimitiveCount = 0;
let previousVisible = Buffer.alloc(6912);
let previousAttributes = Buffer.alloc(768);
let attributeGeneration = 0;
const presentations = [];
const sequenceHash = crypto.createHash('sha256');

while (u8(0x9307) === 0 && refreshes < 100_000) {
  const status = core.runFrame();
  if (status !== 0) throw new Error(`emulator status ${status}`);
  refreshes++;
  const presentation = u16(0x9308);
  if (presentation === lastPresentation) continue;
  if (presentation !== lastPresentation + 1) {
    throw new Error(`presentation jump ${lastPresentation} -> ${presentation}`);
  }

  const bank = u8(0x9332) ? 7 : 5;
  const visible = Buffer.from(memory.subarray(page(bank), page(bank) + 6912));
  const bitmap = visible.subarray(0, 6144);
  const attributes = visible.subarray(6144);
  const dirtyBase = bank === 5 ? 0x9000 : 0x9060;
  let dirtyCells = 0;
  for (let index = 0; index < 96; index++) dirtyCells += popcount[u8(dirtyBase + index)];
  let changedBitmapBytes = 0;
  let changedBitmapBits = 0;
  for (let index = 0; index < bitmap.length; index++) {
    const difference = bitmap[index] ^ previousVisible[index];
    if (difference) changedBitmapBytes++;
    changedBitmapBits += popcount[difference];
  }
  let changedAttributeBytes = 0;
  for (let index = 0; index < attributes.length; index++) {
    if (attributes[index] !== previousAttributes[index]) changedAttributeBytes++;
  }
  if (presentation === 1 || changedAttributeBytes) attributeGeneration++;

  const primitiveCount = bank5u16(0x7283);
  const cumulativeTstates = refreshes * FRAME_TSTATES_128K + core.getTStates();
  const indexBytes = Buffer.allocUnsafe(2);
  indexBytes.writeUInt16LE(presentation);
  sequenceHash.update(indexBytes);
  sequenceHash.update(visible);
  if (capturesDir) {
    fs.writeFileSync(
      path.join(capturesDir, `frame-${String(presentation).padStart(3, '0')}.scr`),
      visible,
    );
  }
  presentations.push({
    presentation,
    vm_tick: u16(0x9300),
    physical_bank: bank,
    cumulative_refreshes: refreshes,
    refresh_cost: refreshes - lastPresentationRefresh,
    cumulative_tstates_at_refresh_boundary: cumulativeTstates,
    tstate_cost_at_refresh_boundary: cumulativeTstates - lastPresentationTstates,
    primitive_count: delta16(primitiveCount, previousPrimitiveCount),
    cumulative_primitive_count: primitiveCount,
    dirty_cells_for_next_reuse: dirtyCells,
    background_restore_bitmap_bytes_for_next_reuse: dirtyCells * 8,
    visible_changed_bitmap_bytes: changedBitmapBytes,
    visible_changed_bitmap_bits: changedBitmapBits,
    changed_attribute_bytes: changedAttributeBytes,
    attribute_generation: attributeGeneration,
    baseline_attribute_copy_bytes: 1536,
    screen_sha256: sha256(visible),
  });
  previousVisible = visible;
  previousAttributes = Buffer.from(attributes);
  previousPrimitiveCount = primitiveCount;
  lastPresentation = presentation;
  lastPresentationRefresh = refreshes;
  lastPresentationTstates = cumulativeTstates;
}

// The final dirty map for each bank is never restored because playback ends.
const lastIndexByBank = new Map();
for (let index = 0; index < presentations.length; index++) {
  lastIndexByBank.set(presentations[index].physical_bank, index);
}
let restoredBitmapBytes = 0;
for (let index = 0; index < presentations.length; index++) {
  const item = presentations[index];
  const consumed = lastIndexByBank.get(item.physical_bank) !== index;
  item.background_restore_consumed_later = consumed;
  if (consumed) restoredBitmapBytes += item.background_restore_bitmap_bytes_for_next_reuse;
}

const refreshCosts = presentations.map(item => item.refresh_cost);
const tstateCosts = presentations.map(item => item.tstate_cost_at_refresh_boundary);
const totalTstates = refreshes * FRAME_TSTATES_128K + core.getTStates();
const report = {
  schema: 'another-spectrum-baseline-profile-v1',
  measurement: {
    emulator: 'JSSpeccy core',
    machine: 'ZX Spectrum 128K PAL',
    frame_tstates: FRAME_TSTATES_128K,
    presentation_tstates_are_refresh_boundary_samples: true,
  },
  snapshot: {
    path: path.basename(snapshotPath),
    bytes: sna.length,
    sha256: sha256(sna),
  },
  completed: u8(0x9307) === 1,
  renderer_error: bank5u8(0x7282),
  error_opcode: u8(0x9306),
  vm_tick: u16(0x9300),
  instruction_count: u16(0x9302),
  trace_hash: u16(0x9304),
  retained_presentations: presentations.length,
  total_refreshes: refreshes,
  total_tstates_at_refresh_boundary: totalTstates,
  equivalent_seconds_at_50hz: refreshes / 50,
  primitive_count: bank5u16(0x7283),
  presentation_cost: {
    average_refreshes: refreshCosts.reduce((sum, value) => sum + value, 0) / refreshCosts.length,
    p50_refreshes: percentile(refreshCosts, 0.5),
    p95_refreshes: percentile(refreshCosts, 0.95),
    maximum_refreshes: Math.max(...refreshCosts),
    average_tstates_at_refresh_boundary: tstateCosts.reduce((sum, value) => sum + value, 0) / tstateCosts.length,
    p95_tstates_at_refresh_boundary: percentile(tstateCosts, 0.95),
  },
  bitmap: {
    visible_changed_bytes: presentations.reduce((sum, item) => sum + item.visible_changed_bitmap_bytes, 0),
    visible_changed_bits: presentations.reduce((sum, item) => sum + item.visible_changed_bitmap_bits, 0),
    background_restore_bytes: restoredBitmapBytes,
    rasterizer_write_bytes: null,
    rasterizer_write_bytes_note: 'Requires the separately instrumented byte-write build; framebuffer deltas are not write counts.',
  },
  attributes: {
    generations: attributeGeneration,
    baseline_copy_bytes: presentations.length * 1536,
    baseline_copy_policy: '768 bytes copied to bank 5 and bank 7 on every retained presentation',
    visible_changed_bytes: presentations.reduce((sum, item) => sum + item.changed_attribute_bytes, 0),
  },
  page_copy: {
    bitmap_bytes: null,
    note: 'Filled by semantic trace analysis; page operations are not distinguishable from framebuffer deltas.',
  },
  screen_sequence_sha256: sequenceHash.digest('hex'),
  presentations,
};
fs.mkdirSync(path.dirname(outputPath), { recursive: true });
fs.writeFileSync(outputPath, JSON.stringify(report, null, 2) + '\n');
console.log(JSON.stringify({ ...report, presentations: undefined }, null, 2));
if (!report.completed || report.renderer_error || report.error_opcode) process.exitCode = 1;
