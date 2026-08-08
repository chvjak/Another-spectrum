#!/usr/bin/env node
/** Read measurement-only counters once per refresh and prove visual identity. */
import crypto from 'node:crypto';
import fs from 'node:fs';

const [wasmPath, snapshotPath, baselineProfilePath, outputPath] = process.argv.slice(2);
if (!outputPath) {
  throw new Error(
    'usage: profile_instrumented_snapshot.mjs core.wasm profile.sna baseline-profile.json output.json',
  );
}

const sna = fs.readFileSync(snapshotPath);
const wasm = fs.readFileSync(wasmPath);
const baseline = JSON.parse(fs.readFileSync(baselineProfilePath, 'utf8'));
const { instance } = await WebAssembly.instantiate(wasm);
const core = instance.exports;
const memory = new Uint8Array(core.memory.buffer);
const registers = new Uint16Array(core.memory.buffer, core.REGISTERS, 12);
const page = bank => core.MACHINE_MEMORY + bank * 0x4000;
const load = (bank, offset) => memory.set(sna.subarray(offset, offset + 0x4000), page(bank));
core.setMachineType(128);
memory.fill(0, page(8), page(10));
load(5, 27);
load(2, 27 + 0x4000);
load(0, 27 + 0x8000);
let offset = 49_183;
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
core.writePort(0xfe, 0);
core.writePort(0x7ffd, 0);
core.setTStates(0);

const fixed = address => page(2) + address - 0x8000;
const u8 = address => memory[fixed(address)];
const u16 = address => u8(address) | (u8(address + 1) << 8);
const bank5u8 = address => memory[page(5) + address - 0x4000];
const counters = [
  ['span_bytes', 0x9360],
  ['text_bytes', 0x9362],
  ['full_bitmap_bytes', 0x9364],
  ['polygons', 0x9366],
  ['points', 0x9368],
  ['background_primitives', 0x936a],
  ['foreground_primitives', 0x936c],
  ['background_span_bytes', 0x936e],
  ['foreground_span_bytes', 0x9370],
];
const previous = Object.fromEntries(counters.map(([name]) => [name, 0]));
const totals = Object.fromEntries(counters.map(([name]) => [name, 0]));
let currentPresentation = Object.fromEntries(counters.map(([name]) => [name, 0]));
const delta16 = (current, prior) => (current - prior + 0x10000) & 0xffff;
const sequence = crypto.createHash('sha256');
const presentations = [];
let refreshes = 0;
let seen = 0;

while (u8(0x9307) === 0 && refreshes < 200_000) {
  const status = core.runFrame();
  if (status) throw new Error(`emulator status ${status}`);
  refreshes++;
  for (const [name, address] of counters) {
    const value = u16(address);
    const increment = delta16(value, previous[name]);
    previous[name] = value;
    totals[name] += increment;
    currentPresentation[name] += increment;
  }
  const presentation = u16(0x9308);
  if (presentation === seen) continue;
  if (presentation !== seen + 1) throw new Error(`presentation jump ${seen} -> ${presentation}`);
  const bank = u8(0x9332) ? 7 : 5;
  const screen = memory.subarray(page(bank), page(bank) + 6912);
  const index = Buffer.allocUnsafe(2);
  index.writeUInt16LE(presentation);
  sequence.update(index);
  sequence.update(screen);
  presentations.push({
    presentation,
    vm_tick: u16(0x9300),
    ...currentPresentation,
  });
  currentPresentation = Object.fromEntries(counters.map(([name]) => [name, 0]));
  seen = presentation;
}

const screenSequenceSha256 = sequence.digest('hex');
const report = {
  schema: 'another-spectrum-instrumented-profile-v1',
  measurement_only: true,
  completed: u8(0x9307) === 1,
  renderer_error: bank5u8(0x7282),
  error_opcode: u8(0x9306),
  vm_tick: u16(0x9300),
  instruction_count: u16(0x9302),
  trace_hash: u16(0x9304),
  presentations: seen,
  instrumented_refreshes: refreshes,
  baseline_refreshes: baseline.total_refreshes,
  screen_sequence_sha256: screenSequenceSha256,
  expected_screen_sequence_sha256: baseline.screen_sequence_sha256,
  visual_identity: screenSequenceSha256 === baseline.screen_sequence_sha256,
  totals: {
    ...totals,
    rasterizer_and_text_bitmap_write_bytes: totals.span_bytes + totals.text_bytes,
    primitive_sum: totals.polygons + totals.points,
    destination_primitive_sum: totals.background_primitives + totals.foreground_primitives,
    span_destination_sum: totals.background_span_bytes + totals.foreground_span_bytes,
  },
  per_presentation: presentations,
};
fs.writeFileSync(outputPath, JSON.stringify(report, null, 2) + '\n');
console.log(JSON.stringify({ ...report, per_presentation: undefined }, null, 2));
if (
  !report.completed ||
  report.renderer_error ||
  report.error_opcode ||
  !report.visual_identity ||
  report.totals.primitive_sum !== baseline.primitive_count ||
  report.totals.destination_primitive_sum !== baseline.primitive_count ||
  report.totals.span_destination_sum !== report.totals.span_bytes
) {
  process.exitCode = 1;
}
