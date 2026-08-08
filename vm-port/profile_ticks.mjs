#!/usr/bin/env node
/** Measure real-geometry VM tick latency at JSSpeccy's 128K PAL boundary. */
import crypto from 'node:crypto';
import fs from 'node:fs';
import path from 'node:path';

const [wasmPath, snapshotPath, outputPath, mode] = process.argv.slice(2);
if (!outputPath) {
  throw new Error('usage: profile_ticks.mjs core.wasm snapshot.sna output.json');
}

const FRAME_TSTATES = 70_908;
const BANK_BYTES = 0x4000;
const sna = fs.readFileSync(snapshotPath);
if (sna.length !== 131_103) throw new Error(`unexpected SNA size ${sna.length}`);
const { instance } = await WebAssembly.instantiate(fs.readFileSync(wasmPath));
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
let offset = 49_183;
for (const bank of [1, 3, 4, 6, 7]) {
  load(bank, offset);
  offset += BANK_BYTES;
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
const sha256 = bytes => crypto.createHash('sha256').update(bytes).digest('hex');
const delta16 = (current, previous) => (current - previous + 0x10000) & 0xffff;
const counterAddresses = {
  span_bytes: 0x9360,
  text_bytes: 0x9362,
  full_bitmap_bytes: 0x9364,
  polygons: 0x9366,
  points: 0x9368,
  background_primitives: 0x936a,
  foreground_primitives: 0x936c,
  background_span_bytes: 0x936e,
  foreground_span_bytes: 0x9370,
};
const instrumented = mode === 'instrumented';
let previousCounters = Object.fromEntries(
  Object.entries(counterAddresses).map(([name, address]) => [name, u16(address)]),
);
let segmentCounters = Object.fromEntries(Object.keys(counterAddresses).map(name => [name, 0]));

let refresh = 0;
let previousTick = u16(0x9300);
let previousTransitionRefresh = 0;
const ticks = [];
while (u8(0x9307) === 0 && refresh < 100_000) {
  const status = core.runFrame();
  if (status !== 0) throw new Error(`emulator status ${status}`);
  refresh++;
  if (instrumented) {
    for (const [name, address] of Object.entries(counterAddresses)) {
      const current = u16(address);
      segmentCounters[name] += delta16(current, previousCounters[name]);
      previousCounters[name] = current;
    }
  }
  const currentTick = u16(0x9300);
  if (currentTick === previousTick) continue;
  const elapsed = refresh - previousTransitionRefresh;
  const advanced = (currentTick - previousTick + 0x10000) & 0xffff;
  const tickEntry = {
    completed_tick_first: previousTick,
    completed_tick_last: currentTick - 1,
    ticks_advanced: advanced,
    boundary_refreshes: elapsed,
    boundary_tstates: elapsed * FRAME_TSTATES,
    average_boundary_refreshes_per_tick: elapsed / advanced,
  };
  if (instrumented) tickEntry.instrumented_counters = segmentCounters;
  ticks.push(tickEntry);
  segmentCounters = Object.fromEntries(Object.keys(counterAddresses).map(name => [name, 0]));
  previousTick = currentTick;
  previousTransitionRefresh = refresh;
}

const report = {
  schema: 'another-spectrum-tick-profile-v1',
  measurement: {
    emulator: 'JSSpeccy core',
    machine: 'ZX Spectrum 128K PAL',
    frame_tstates: FRAME_TSTATES,
    granularity: 'refresh boundary; multiple cheap catch-up ticks may share one sample',
    instrumented_counters: instrumented,
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
  total_refreshes: refresh,
  equivalent_seconds_at_50hz: refresh / 50,
  ticks,
};
fs.mkdirSync(path.dirname(outputPath), { recursive: true });
fs.writeFileSync(outputPath, JSON.stringify(report, null, 2) + '\n');
console.log(JSON.stringify({ ...report, ticks: undefined }, null, 2));
if (!report.completed || report.renderer_error || report.error_opcode) process.exitCode = 1;
