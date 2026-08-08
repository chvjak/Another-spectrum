#!/usr/bin/env node
/** Instruction-granular run_tasks timings for a measurement-only VM build. */
import crypto from 'node:crypto';
import fs from 'node:fs';
import path from 'node:path';

const [wasmPath, snapshotPath, outputPath, quantumArg, counterMode] = process.argv.slice(2);
if (!outputPath) {
  throw new Error('usage: profile_exact_ticks.mjs core.wasm snapshot.sna output.json [quantum-tstates]');
}
const QUANTUM = Number(quantumArg ?? 64);
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
const instrumentedCounters = counterMode !== 'timing-only';
const readCounters = () => Object.fromEntries(
  Object.entries(counterAddresses).map(([name, address]) => [name, u16(address)]),
);

let frame = 0;
let absoluteTstates = 0;
let previousLocalTstates = 0;
let previousPhase = u8(0x9374);
let phaseStart = null;
let phaseTick = null;
let phaseCounters = null;
const ticks = [];

while (u8(0x9307) === 0 && frame < 100_000) {
  const local = core.getTStates();
  const target = Math.min(local + QUANTUM, FRAME_TSTATES);
  const status = core.runUntil(target);
  if (status !== 0) throw new Error(`emulator status ${status}`);
  let nowLocal = core.getTStates();
  absoluteTstates += nowLocal - previousLocalTstates;
  previousLocalTstates = nowLocal;

  const phase = u8(0x9374);
  if (phase !== previousPhase) {
    if (phase) {
      phaseStart = absoluteTstates;
      phaseTick = u16(0x9300);
      phaseCounters = instrumentedCounters ? readCounters() : null;
    } else if (phaseStart !== null) {
      const entry = {
        tick: phaseTick,
        run_tasks_tstates: absoluteTstates - phaseStart,
        run_tasks_refreshes: (absoluteTstates - phaseStart) / FRAME_TSTATES,
      };
      if (instrumentedCounters && phaseCounters !== null) {
        const endCounters = readCounters();
        entry.counters = Object.fromEntries(
          Object.keys(counterAddresses).map(name => [
            name,
            delta16(endCounters[name], phaseCounters[name]),
          ]),
        );
      }
      ticks.push(entry);
      phaseStart = null;
      phaseTick = null;
      phaseCounters = null;
    }
    previousPhase = phase;
  }

  if (nowLocal >= FRAME_TSTATES) {
    // runUntil has reached the PAL boundary. runFrame performs the core's
    // normal framebuffer/audio finalisation and subtracts one frame without
    // executing another frame because t is already at the boundary.
    const frameStatus = core.runFrame();
    if (frameStatus !== 0) throw new Error(`frame finalisation status ${frameStatus}`);
    frame++;
    nowLocal = core.getTStates();
    previousLocalTstates = nowLocal;
  }
}

const report = {
  schema: 'another-spectrum-exact-tick-profile-v1',
  measurement: {
    emulator: 'JSSpeccy core',
    machine: 'ZX Spectrum 128K PAL',
    frame_tstates: FRAME_TSTATES,
    polling_quantum_tstates: QUANTUM,
    timing_error_bound_tstates: QUANTUM * 2,
    scope: 'VM run_tasks only; excludes scheduler wait_tick_slot and setup_tasks',
    measurement_only_counter_overhead: true,
    instrumented_counters: instrumentedCounters,
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
  elapsed_refreshes: frame,
  ticks,
};
fs.mkdirSync(path.dirname(outputPath), { recursive: true });
fs.writeFileSync(outputPath, JSON.stringify(report, null, 2) + '\n');
console.log(JSON.stringify({ ...report, ticks: undefined, measured_ticks: ticks.length }, null, 2));
if (!report.completed || report.renderer_error || report.error_opcode || ticks.length !== 2980) {
  process.exitCode = 1;
}
