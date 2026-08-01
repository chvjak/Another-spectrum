import fs from 'node:fs';
import path from 'node:path';

const [wasmPath, rom0Path, rom1Path, snapshotPath, outputDir] = process.argv.slice(2);
if (!outputDir) {
  throw new Error('usage: capture_snapshot_screens.mjs core.wasm rom0 rom1 snapshot.sna output-dir');
}

const sna = fs.readFileSync(snapshotPath);
const wasm = fs.readFileSync(wasmPath);
const rom0 = fs.readFileSync(rom0Path);
const rom1 = fs.readFileSync(rom1Path);
fs.mkdirSync(outputDir, { recursive: true });

const { instance } = await WebAssembly.instantiate(wasm);
const core = instance.exports;
const memory = new Uint8Array(core.memory.buffer);
const regs = new Uint16Array(core.memory.buffer, core.REGISTERS, 12);
const page = bank => core.MACHINE_MEMORY + bank * 0x4000;
const load = (bank, offset) => memory.set(sna.subarray(offset, offset + 0x4000), page(bank));

core.setMachineType(128);
memory.set(rom0, page(8));
memory.set(rom1, page(9));
load(5, 27); load(2, 27 + 0x4000); load(0, 27 + 0x8000);
let offset = 49183;
for (const bank of [1, 3, 4, 6, 7]) { load(bank, offset); offset += 0x4000; }
regs.fill(0); regs[10] = 0xBFF0;
core.setPC(0x8000); core.setIFF1(0); core.setIFF2(0); core.setIM(1);
core.setHalted(false); core.writePort(0x00FE, 0); core.writePort(0x7FFD, 0); core.setTStates(0);

const fixed = address => page(2) + address - 0x8000;
const u8 = address => memory[fixed(address)];
const u16 = address => u8(address) | (u8(address + 1) << 8);
let seen = 0;
let refreshes = 0;
while (u8(0x9307) === 0 && refreshes < 40000) {
  const status = core.runFrame();
  if (status) throw new Error(`emulator status ${status}`);
  refreshes++;
  const count = u16(0x9308);
  if (count === seen) continue;
  const bank = u8(0x9332) === 0 ? 5 : 7;
  fs.writeFileSync(path.join(outputDir, `frame-${String(count).padStart(3, '0')}.scr`),
    memory.subarray(page(bank), page(bank) + 6912));
  seen = count;
}
console.log(JSON.stringify({ refreshes, presentations: seen, vmTick: u16(0x9300), finished: u8(0x9307) }));
if (u8(0x9307) !== 1) process.exitCode = 1;
