#!/usr/bin/env node
import crypto from 'node:crypto';
import fs from 'node:fs';
import path from 'node:path';

const [command, wasmPath, buildDir, ...rest] = process.argv.slice(2);
if (!command || !wasmPath || !buildDir) {
  throw new Error('usage: final_perf_runner.mjs trace|matrix|elide core.wasm build-dir ...');
}
const wasm = fs.readFileSync(wasmPath);
const TRACE_OFFSET = 0x2600;
const TRACE_RECORD_SIZE = 103;
const TRACE_CAPACITY = 64;
const SCRIPT_OFFSET = 0x2630;

function snapshotBankOffset(bank) {
  if (bank === 5) return 27;
  if (bank === 2) return 27 + 0x4000;
  if (bank === 0) return 27 + 0x8000;
  return 49183 + [1, 3, 4, 6, 7].indexOf(bank) * 0x4000;
}

async function setupCore(sna) {
  const { instance } = await WebAssembly.instantiate(wasm);
  const core = instance.exports;
  const memory = new Uint8Array(core.memory.buffer);
  const regs = new Uint16Array(core.memory.buffer, core.REGISTERS, 12);
  const pageAddress = bank => core.MACHINE_MEMORY + bank * 0x4000;
  const loadPage = (bank, sourceOffset) => memory.set(
    sna.subarray(sourceOffset, sourceOffset + 0x4000), pageAddress(bank));
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

async function runSna(sna, label, collectTrace = false) {
  const { core, memory, pageAddress, u8, u16, b5u8, b5u16 } = await setupCore(sna);
  const visibleHash = crypto.createHash('sha256');
  const bothHash = crypto.createHash('sha256');
  let lastPresentation = 0;
  let hostFrames = 0;
  let lastTraceSeq = 0;
  const traceRecords = [];
  while (u8(0x9307) === 0 && hostFrames < 300000) {
    const status = core.runFrame();
    if (status !== 0) throw new Error(`${label}: core status ${status}`);
    hostFrames++;
    if (collectTrace) {
      const seq = u16(0x93D8);
      const delta = (seq - lastTraceSeq + 0x10000) & 0xFFFF;
      if (delta > TRACE_CAPACITY) throw new Error(`trace ring overrun ${lastTraceSeq}->${seq}`);
      let consumedSeq = lastTraceSeq;
      for (let n = 1; n <= delta; n++) {
        const expected = (lastTraceSeq + n) & 0xFFFF;
        const slot = (expected - 1) & (TRACE_CAPACITY - 1);
        const base = pageAddress(7) + TRACE_OFFSET + slot * TRACE_RECORD_SIZE;
        const actual = memory[base] | (memory[base + 1] << 8);
        if (actual !== expected) {
          // FINAL_TRACE_SEQ is incremented before the 103-byte record is fully
          // copied. A 50 Hz host boundary may therefore observe the new global
          // sequence while its ring slot still contains the record from one
          // complete wrap ago. Defer only that newest in-flight record.
          const previousWrap = (expected - TRACE_CAPACITY) & 0xFFFF;
          if (n === delta && actual === previousWrap) break;
          throw new Error(`trace seq mismatch ${expected} != ${actual}`);
        }
        const target = memory[base + 2];
        const presentation = memory[base + 3] | (memory[base + 4] << 8);
        const tick = memory[base + 5] | (memory[base + 6] << 8);
        const mask = Buffer.from(memory.subarray(base + 7, base + 103));
        traceRecords.push({ sequence: actual, target_screen: target, presentation, vm_tick: tick, mask_hex: mask.toString('hex') });
        consumedSeq = expected;
      }
      lastTraceSeq = consumedSeq;
    }
    const presentation = u16(0x9308);
    if (presentation === lastPresentation) continue;
    if (presentation !== lastPresentation + 1) throw new Error(`${label}: presentation jump ${lastPresentation}->${presentation}`);
    const index = Buffer.allocUnsafe(2); index.writeUInt16LE(presentation);
    const displayBank = (u8(0x930B) & 8) ? 7 : 5;
    visibleHash.update(index);
    visibleHash.update(memory.subarray(pageAddress(displayBank), pageAddress(displayBank) + 6912));
    bothHash.update(index);
    bothHash.update(memory.subarray(pageAddress(5), pageAddress(5) + 6912));
    bothHash.update(memory.subarray(pageAddress(7), pageAddress(7) + 6912));
    lastPresentation = presentation;
  }
  return {
    label,
    done: u8(0x9307), host_frames: hostFrames, seconds_at_50hz: hostFrames / 50,
    vm_tick: u16(0x9300), instruction_count: u16(0x9302), trace_hash: u16(0x9304),
    error_opcode: u8(0x9306), sampled_frames: u16(0x9308),
    visible_sequence_sha256: visibleHash.digest('hex'),
    both_screens_sequence_sha256: bothHash.digest('hex'),
    decoded_primitives: b5u16(0x7283), renderer_error: b5u8(0x7282),
    renderer_error_root: b5u16(0x72A2), renderer_error_shape: b5u16(0x729D),
    renderer_error_code: b5u8(0x729F), restore_calls_consumed: u16(0x93D4),
    trace_records: traceRecords,
  };
}

async function doTrace() {
  const sna = fs.readFileSync(path.join(buildDir, 'final-trace.sna'));
  const run = await runSna(sna, 'final-trace', true);
  const output = { run: { ...run, trace_records: undefined }, records: run.trace_records };
  fs.writeFileSync(path.join(buildDir, 'restore-trace.json'), JSON.stringify(output, null, 2) + '\n');
  console.log(JSON.stringify({ calls: output.records.length, run: output.run }, null, 2));
  if (run.done !== 1 || run.error_opcode || run.renderer_error) process.exitCode = 1;
}

function valid(run) { return run.done === 1 && run.error_opcode === 0 && run.renderer_error === 0; }
function sameTrace(a, b) { return a.vm_tick === b.vm_tick && a.instruction_count === b.instruction_count && a.trace_hash === b.trace_hash; }

async function doMatrix() {
  const labels = rest.length ? rest : ['ega-best','restore','script-arith','script-table','script-table-ldi','script-table-ldi-lazy','combined'];
  const runs = {};
  for (const label of labels) runs[label] = await runSna(fs.readFileSync(path.join(buildDir, `${label}.sna`)), label);
  const reference = runs[labels[0]];
  const comparisons = {};
  for (const label of labels.slice(1)) {
    const r = runs[label];
    comparisons[label] = {
      passed: valid(r), trace_equal: sameTrace(reference, r),
      primitives_equal: r.decoded_primitives === reference.decoded_primitives,
      visible_equal: r.visible_sequence_sha256 === reference.visible_sequence_sha256,
      both_screens_equal: r.both_screens_sequence_sha256 === reference.both_screens_sequence_sha256,
      speedup: reference.host_frames / r.host_frames,
      saved_percent: (1 - r.host_frames / reference.host_frames) * 100,
      saved_refreshes: reference.host_frames - r.host_frames,
    };
  }
  const eligible = labels.filter(label => valid(runs[label]) && sameTrace(reference, runs[label]) && runs[label].visible_sequence_sha256 === reference.visible_sequence_sha256);
  const winner = eligible.reduce((a,b) => runs[b].host_frames < runs[a].host_frames ? b : a, eligible[0]);
  const result = { passed: valid(reference) && Object.values(comparisons).every(c => c.passed && c.trace_equal && c.primitives_equal && c.visible_equal), reference: labels[0], winner, runs, comparisons };
  fs.writeFileSync(path.join(buildDir, 'final-perf-result.json'), JSON.stringify(result, null, 2) + '\n');
  console.log(JSON.stringify(result, null, 2));
  if (!result.passed) process.exitCode = 1;
}

function patchScriptIntoSna(baseSna, script) {
  const out = Buffer.from(baseSna);
  const start = snapshotBankOffset(7) + SCRIPT_OFFSET;
  script.copy(out, start);
  return out;
}

async function doElide() {
  const metaPath = rest[0] || path.join(buildDir, 'restore-script-meta.json');
  const scriptPath = rest[1] || path.join(buildDir, 'restore-script.bin');
  const maxTests = Number(rest[2] || 120);
  const meta = JSON.parse(fs.readFileSync(metaPath));
  const originalScript = fs.readFileSync(scriptPath);
  const baseSna = fs.readFileSync(path.join(buildDir, 'script-table-ldi.sna'));
  const baseline = await runSna(baseSna, 'script-table-ldi-baseline');
  const acceptedCalls = new Set();
  const acceptedRunHighBytes = new Set();
  let tests = 0;

  function candidateScript(extraCalls = [], extraRuns = []) {
    const s = Buffer.from(originalScript);
    for (const idx of [...acceptedCalls, ...extraCalls]) {
      const rec = meta.records[idx];
      if (rec.run_count === 0xFFFF) s[rec.opcode_offset] = 0xC0;
      else s[rec.opcode_offset] = 0xC0 | rec.run_count;
    }
    for (const off of [...acceptedRunHighBytes, ...extraRuns]) s[off] |= 0x80;
    return s;
  }
  async function passes(extraCalls = [], extraRuns = []) {
    if (tests >= maxTests) return false;
    tests++;
    const sna = patchScriptIntoSna(baseSna, candidateScript(extraCalls, extraRuns));
    const run = await runSna(sna, `elide-${tests}`);
    return valid(run) && sameTrace(baseline, run) && run.visible_sequence_sha256 === baseline.visible_sequence_sha256;
  }
  async function recurseCalls(group) {
    if (!group.length || tests >= maxTests) return;
    if (await passes(group, [])) { for (const x of group) acceptedCalls.add(x); return; }
    if (group.length === 1) return;
    const mid = Math.floor(group.length / 2);
    await recurseCalls(group.slice(0, mid)); await recurseCalls(group.slice(mid));
  }
  const callCandidates = meta.records.filter(r => r.run_count !== 0).map(r => r.index);
  await recurseCalls(callCandidates);

  const rowGroups = [];
  for (const rec of meta.records) {
    if (acceptedCalls.has(rec.index)) continue;
    for (const g of rec.row_groups) if (g.high_byte_offsets.length) rowGroups.push(g.high_byte_offsets);
  }
  async function recurseRows(groups) {
    if (!groups.length || tests >= maxTests) return;
    const flat = groups.flat();
    if (await passes([], flat)) { for (const x of flat) acceptedRunHighBytes.add(x); return; }
    if (groups.length === 1) return;
    const mid = Math.floor(groups.length / 2);
    await recurseRows(groups.slice(0, mid)); await recurseRows(groups.slice(mid));
  }
  await recurseRows(rowGroups);

  const finalScript = candidateScript();
  fs.writeFileSync(path.join(buildDir, 'restore-script-elided.bin'), finalScript);
  const finalSna = patchScriptIntoSna(baseSna, finalScript);
  fs.writeFileSync(path.join(buildDir, 'final.sna'), finalSna);
  const finalRun = await runSna(finalSna, 'final');
  const report = {
    tests, max_tests: maxTests, elided_calls: acceptedCalls.size,
    elided_row_runs: acceptedRunHighBytes.size,
    baseline, final: finalRun,
    visible_equal: finalRun.visible_sequence_sha256 === baseline.visible_sequence_sha256,
    saved_refreshes: baseline.host_frames - finalRun.host_frames,
    saved_percent: (1 - finalRun.host_frames / baseline.host_frames) * 100,
  };
  fs.writeFileSync(path.join(buildDir, 'restore-elision-result.json'), JSON.stringify(report, null, 2) + '\n');
  console.log(JSON.stringify(report, null, 2));
  if (!valid(finalRun) || !sameTrace(baseline, finalRun) || !report.visible_equal) process.exitCode = 1;
}

if (command === 'trace') await doTrace();
else if (command === 'matrix') await doMatrix();
else if (command === 'elide') await doElide();
else throw new Error(`unknown command ${command}`);
