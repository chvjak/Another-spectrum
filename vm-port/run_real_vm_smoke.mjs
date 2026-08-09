import fs from 'node:fs';

const rawArgs = process.argv.slice(2);
const siteBaseline = rawArgs.includes('--site-baseline');
const args = rawArgs.filter(arg => arg !== '--site-baseline');
const [wasmPath, rom0Path, rom1Path, snapshotPath] = args;
if (!wasmPath || !rom0Path || !rom1Path || !snapshotPath) {
  throw new Error('usage: run_real_vm_smoke.mjs core.wasm 128-0.rom 128-1.rom snapshot.sna [--site-baseline]');
}

const sna = fs.readFileSync(snapshotPath);
const wasm = fs.readFileSync(wasmPath);
const rom0 = fs.readFileSync(rom0Path);
const rom1 = fs.readFileSync(rom1Path);
const { instance } = await WebAssembly.instantiate(wasm);
const core = instance.exports;
const memory = new Uint8Array(core.memory.buffer);
const regs = new Uint16Array(core.memory.buffer, core.REGISTERS, 12);
const page = bank => core.MACHINE_MEMORY + bank * 0x4000;
const loadPage = (bank, offset) =>
  memory.set(sna.subarray(offset, offset + 0x4000), page(bank));

if (sna.length !== 131103) throw new Error(`unexpected SNA size: ${sna.length}`);
core.setMachineType(128);
memory.set(rom0, page(8));
memory.set(rom1, page(9));
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

const fixed = address => page(2) + address - 0x8000;
const u8 = address => memory[fixed(address)];
const u16 = address => u8(address) | (u8(address + 1) << 8);
const bank5u8 = address => memory[page(5) + address - 0x4000];

let hostFrames = 0;
while (u8(0x9307) === 0 && hostFrames < 100000) {
  const status = core.runFrame();
  if (status !== 0) throw new Error(`emulator stopped with status ${status}`);
  hostFrames++;
}

const result = {
  validation_mode: siteBaseline ? 'site-baseline' : 'canonical-snapshot',
  passed: siteBaseline
    ? u8(0x9307) === 1 && u16(0x9300) === 2980 && u16(0x9308) > 0 && bank5u8(0x7282) === 0
    : u8(0x9307) === 1 &&
      u8(0x9306) === 0 &&
      u16(0x9300) === 2980 &&
      u16(0x9302) === 56075 &&
      u16(0x9304) === 0x9EF3 &&
      bank5u8(0x7282) === 0,
  host_frames: hostFrames,
  vm_tick: u16(0x9300),
  instruction_count: u16(0x9302),
  trace_hash: `0x${u16(0x9304).toString(16).padStart(4, '0')}`,
  sampled_frames: u16(0x9308),
  renderer_error: bank5u8(0x7282),
  renderer_error_code: bank5u8(0x729F),
  dense_restore_threshold: 512,
  pc: `0x${core.getPC().toString(16).padStart(4, '0')}`,
  sp: `0x${regs[10].toString(16).padStart(4, '0')}`,
};

console.log(JSON.stringify(result, null, 2));
if (!result.passed) process.exitCode = 1;
