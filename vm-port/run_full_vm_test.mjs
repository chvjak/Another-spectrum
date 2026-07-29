import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const here = path.dirname(fileURLToPath(import.meta.url));
const build = path.join(here, 'build-full');
const sna = fs.readFileSync(path.join(build, 'another-world-vm-full.sna'));
const manifest = JSON.parse(fs.readFileSync(path.join(build, 'manifest.json'), 'utf8'));
const wasm = fs.readFileSync(path.join(here, '..', 'jsspeccy-core.wasm'));
const rom0 = fs.readFileSync(path.join(here, '..', 'rom-128-0.bin'));
const rom1 = fs.readFileSync(path.join(here, '..', 'rom-128-1.bin'));

const { instance } = await WebAssembly.instantiate(wasm);
const core = instance.exports;
const memory = new Uint8Array(core.memory.buffer);
const regs = new Uint16Array(core.memory.buffer, core.REGISTERS, 12);
const pageAddress = bank => core.MACHINE_MEMORY + bank * 0x4000;
const loadPage = (bank, sourceOffset) =>
  memory.set(sna.subarray(sourceOffset, sourceOffset + 0x4000), pageAddress(bank));

core.setMachineType(128);
memory.set(rom0, pageAddress(8));
memory.set(rom1, pageAddress(9));
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
const u8at = address => memory[fixed(address)];
const u16at = address => u8at(address) | (u8at(address + 1) << 8);
const bank5u8 = address => memory[pageAddress(5) + address - 0x4000];
const bank5u16 = address => bank5u8(address) | (bank5u8(address + 1) << 8);

let hostFrames = 0;
let sampledFrames = 0;
let rendererErrorAt = null;
const samples = [];
const checkpointFrames = new Set([20, 31, 41, 106, 222]);
const checkpointBackgroundMismatches = [];
const dumpDir = process.env.DUMP_SCREENS;
if (dumpDir) fs.mkdirSync(dumpDir, { recursive: true });
while (u8at(0x9307) === 0 && hostFrames < 60000) {
  const status = core.runFrame();
  if (status !== 0) throw new Error(`emulator stopped with status ${status}`);
  hostFrames++;
  if (rendererErrorAt === null && bank5u8(0x7282) !== 0) {
    rendererErrorAt = {
      hostFrame: hostFrames,
      vmTick: u16at(0x9300),
      root: bank5u16(0x72a2),
      currentRoot: bank5u16(0x72a0),
      shape: bank5u16(0x729d),
      code: bank5u8(0x729f),
      pc: core.getPC(),
      sp: regs[10],
      shapeOffset: bank5u16(0x7285),
      centerX: bank5u16(0x7287),
      centerY: bank5u16(0x7289),
      zoom: bank5u16(0x728b),
    };
  }
  const count = u16at(0x9308);
  if (count === sampledFrames) continue;

  const referenceNumber = Math.min(count * 10, 2980);
  const expected = fs.readFileSync(
    path.join(here, '..', 'full-speccy', `frame-${referenceNumber.toString().padStart(4, '0')}.scr`)
  );
  const results = [5, 7].map(bank => {
    const actual = memory.subarray(pageAddress(bank), pageAddress(bank) + 6912);
    let bitmapMismatch = 0;
    let attributeMismatch = 0;
    for (let i = 0; i < 6144; i++) if (actual[i] !== expected[i]) bitmapMismatch++;
    for (let i = 6144; i < 6912; i++) if (actual[i] !== expected[i]) attributeMismatch++;
    return { bank, bitmapMismatch, attributeMismatch };
  });
  results.sort((a, b) =>
    (a.bitmapMismatch + a.attributeMismatch) - (b.bitmapMismatch + b.attributeMismatch)
  );
  samples.push({
    frame: count,
    reference: referenceNumber,
    hostFrame: hostFrames,
    vmTick: u16at(0x9300),
    closest: results[0],
  });
  if (checkpointFrames.has(count)) {
    const referenceFrame = count * 10;
    const checkpoint = fs.readFileSync(
      path.join(build, `checkpoint-${referenceFrame}.bitmap`)
    );
    let mismatch = 0;
    for (let i = 0; i < checkpoint.length; i++) {
      if (memory[fixed(0xA000) + i] !== checkpoint[i]) mismatch++;
    }
    const sampledBank = u8at(0x9332) === 0 ? 5 : 7;
    let screenMismatch = 0;
    for (let i = 0; i < checkpoint.length; i++) {
      if (memory[pageAddress(sampledBank) + i] !== checkpoint[i]) {
        screenMismatch++;
      }
    }
    const dirtyBase = sampledBank === 5 ? 0x9000 : 0x9060;
    let dirtyBytes = 0;
    for (let i = 0; i < 96; i++) {
      if (u8at(dirtyBase + i) !== 0) dirtyBytes++;
    }
    checkpointBackgroundMismatches.push({
      frame: count,
      mismatch,
      sampledBank,
      screenMismatch,
      dirtyBytes,
    });
  }
  sampledFrames = count;
  if (dumpDir) {
    const sampledBank = u8at(0x9332) === 0 ? 5 : 7;
    fs.writeFileSync(
      path.join(dumpDir, `frame-${count.toString().padStart(3, '0')}.scr`),
      memory.subarray(pageAddress(sampledBank), pageAddress(sampledBank) + 6912)
    );
  }
}

const bitmapMismatches = samples.map(sample => sample.closest.bitmapMismatch);
const attributeMismatches = samples.map(sample => sample.closest.attributeMismatch);
const result = {
  passed:
    u8at(0x9307) === 1 &&
    u8at(0x9306) === 0 &&
    u16at(0x9300) === 2980 &&
    u16at(0x9302) === manifest.reference.instruction_count &&
    u16at(0x9304) === manifest.reference.trace_hash &&
    u16at(0x9308) === 298 &&
    bank5u8(0x7282) === 0,
  host_frames: hostFrames,
  vm_tick: u16at(0x9300),
  instruction_count: u16at(0x9302),
  expected_instruction_count: manifest.reference.instruction_count,
  trace_hash: `0x${u16at(0x9304).toString(16).padStart(4, '0')}`,
  expected_trace_hash: `0x${manifest.reference.trace_hash.toString(16).padStart(4, '0')}`,
  error_opcode: `0x${u8at(0x9306).toString(16).padStart(2, '0')}`,
  sampled_frames: u16at(0x9308),
  decoded_primitives: bank5u16(0x7283),
  renderer_error: bank5u8(0x7282),
  renderer_error_shape: `0x${bank5u16(0x729d).toString(16).padStart(4, '0')}`,
  renderer_error_code: `0x${bank5u8(0x729f).toString(16).padStart(2, '0')}`,
  renderer_error_root: `0x${bank5u16(0x72a2).toString(16).padStart(4, '0')}`,
  renderer_error_at: rendererErrorAt,
  checkpoint_background_mismatches: checkpointBackgroundMismatches,
  average_bitmap_mismatch: bitmapMismatches.length
    ? bitmapMismatches.reduce((a, b) => a + b, 0) / bitmapMismatches.length
    : null,
  max_bitmap_mismatch: bitmapMismatches.length ? Math.max(...bitmapMismatches) : null,
  max_attribute_mismatch: attributeMismatches.length ? Math.max(...attributeMismatches) : null,
  samples,
};

fs.writeFileSync(path.join(build, 'test-results.json'), JSON.stringify(result, null, 2) + '\n');
console.log(JSON.stringify({ ...result, samples: samples.filter((_, i) => i % 30 === 0) }, null, 2));
if (!result.passed) process.exitCode = 1;
