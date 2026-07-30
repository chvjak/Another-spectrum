#!/usr/bin/env node
import crypto from 'node:crypto';
import fs from 'node:fs';

const [wasmPath, baselinePath, ayPath, outPath] = process.argv.slice(2);
if (!wasmPath || !baselinePath || !ayPath || !outPath) throw new Error('usage: ay_rt45_runner.mjs core.wasm cost-4p5.sna cost-4p5-ay.sna result.json');
const wasm = fs.readFileSync(wasmPath);
const AY_UPDATE_COUNT = 0x7C10;
const AY_VM_FINISHED = 0x7C12;

async function setupCore(sna) {
  const { instance } = await WebAssembly.instantiate(wasm);
  const core = instance.exports;
  const memory = new Uint8Array(core.memory.buffer);
  const regs = new Uint16Array(core.memory.buffer, core.REGISTERS, 12);
  const pageAddress = bank => core.MACHINE_MEMORY + bank * 0x4000;
  const loadPage = (bank, sourceOffset) => memory.set(sna.subarray(sourceOffset, sourceOffset + 0x4000), pageAddress(bank));
  core.setMachineType(128);
  memory.fill(0, pageAddress(8), pageAddress(10));
  loadPage(5, 27); loadPage(2, 27 + 0x4000); loadPage(0, 27 + 0x8000);
  let sourceOffset = 49183;
  for (const bank of [1, 3, 4, 6, 7]) { loadPage(bank, sourceOffset); sourceOffset += 0x4000; }
  regs.fill(0); regs[10] = 0xBFF0;
  core.setPC(0x8000); core.setIFF1(0); core.setIFF2(0); core.setIM(1);
  core.setHalted(false); core.writePort(0x00FE, 0); core.writePort(0x7FFD, 0); core.setTStates(0);
  const fixed = address => pageAddress(2) + address - 0x8000;
  const u8 = address => memory[fixed(address)];
  const u16 = address => u8(address) | (u8(address + 1) << 8);
  const b5u8 = address => memory[pageAddress(5) + address - 0x4000];
  const b5u16 = address => b5u8(address) | (b5u8(address + 1) << 8);
  return { core, memory, pageAddress, u8, u16, b5u8, b5u16 };
}

function hashScreen(memory, pageAddress, bank) {
  return crypto.createHash('sha256').update(memory.subarray(pageAddress(bank), pageAddress(bank) + 6912)).digest('hex');
}

async function run(snaPath, label, ayPlayer = false) {
  const sna = fs.readFileSync(snaPath);
  const { core, memory, pageAddress, u8, u16, b5u8, b5u16 } = await setupCore(sna);
  let hostFrames = 0, lastPresentation = 0, vmFinishedFrame = null, firstAyUpdateFrame = null, previousAyUpdates = 0;
  const frames = [], ayUpdateFrames = [];
  while (u8(0x9307) === 0 && hostFrames < 300000) {
    const status = core.runFrame();
    if (status !== 0) throw new Error(`${label}: core status ${status}`);
    hostFrames++;
    if (ayPlayer) {
      const updates = b5u16(AY_UPDATE_COUNT);
      if (updates !== previousAyUpdates) {
        if (updates !== previousAyUpdates + 1) throw new Error(`${label}: AY update jump ${previousAyUpdates}->${updates}`);
        ayUpdateFrames.push(hostFrames);
        if (firstAyUpdateFrame === null) firstAyUpdateFrame = hostFrames;
      }
      previousAyUpdates = updates;
      if (vmFinishedFrame === null && b5u8(AY_VM_FINISHED) !== 0) vmFinishedFrame = hostFrames;
    }
    const presentation = u16(0x9308);
    if (presentation === lastPresentation) continue;
    if (presentation !== lastPresentation + 1) throw new Error(`${label}: presentation jump ${lastPresentation}->${presentation}`);
    const displayBank = (u8(0x930B) & 8) ? 7 : 5;
    frames.push({ presentation, source_slot: u16(0x93E8),
      visible_sha256: hashScreen(memory, pageAddress, displayBank) });
    lastPresentation = presentation;
  }
  return {
    label, done: u8(0x9307), host_frames: hostFrames, seconds_at_50hz: hostFrames / 50,
    first_ay_update_frame: firstAyUpdateFrame, ay_update_frames: ayUpdateFrames,
    vm_finished_frame: vmFinishedFrame,
    vm_finished_seconds: vmFinishedFrame === null ? null : vmFinishedFrame / 50,
    vm_tick: u16(0x9300), instruction_count: u16(0x9302), trace_hash: u16(0x9304),
    error_opcode: u8(0x9306), rendered_presentations: u16(0x9308),
    original_sample_slots_consumed: u16(0x93E8), decoded_primitives: b5u16(0x7283),
    renderer_error: b5u8(0x7282), renderer_error_root: b5u16(0x72A2),
    renderer_error_shape: b5u16(0x729D), renderer_error_code: b5u8(0x729F),
    ay_updates: ayPlayer ? b5u16(AY_UPDATE_COUNT) : null, frames,
  };
}

const baseline = await run(baselinePath, 'cost-4p5', false);
const ay = await run(ayPath, 'cost-4p5-ay', true);
const framesEqual = JSON.stringify(ay.frames) === JSON.stringify(baseline.frames);
const traceEqual = ay.vm_tick === baseline.vm_tick && ay.instruction_count === baseline.instruction_count && ay.trace_hash === baseline.trace_hash;
const target = 8226, expectedUpdates = 4103;
let missedUpdateRefreshes = 0;
for (let i = 1; i < ay.ay_update_frames.length; i++) missedUpdateRefreshes += Math.max(0, ay.ay_update_frames[i] - ay.ay_update_frames[i - 1] - 2);
const result = {
  target_refreshes: target, target_seconds: target / 50,
  playback_source_start_tick: 0,
  playback_updates_expected: expectedUpdates, playback_update_rate_hz_nominal: 25,
  missed_update_refreshes: missedUpdateRefreshes,
  baseline, ay, frames_equal: framesEqual, trace_equal: traceEqual,
  compute_margin_refreshes: ay.vm_finished_frame === null ? null : target - ay.vm_finished_frame,
  completion_margin_refreshes: target - ay.host_frames,
  real_time_compute_met: ay.vm_finished_frame !== null && ay.vm_finished_frame <= target,
  exact_duration_met: ay.host_frames === target,
  passed: ay.done === 1 && ay.error_opcode === 0 && ay.renderer_error === 0 && ay.ay_updates === expectedUpdates && ay.ay_update_frames.length === expectedUpdates && framesEqual && traceEqual && ay.host_frames === target,
};
fs.writeFileSync(outPath, JSON.stringify(result, null, 2) + '\n');
console.log(JSON.stringify(result, null, 2));
if (!result.passed) process.exitCode = 1;
