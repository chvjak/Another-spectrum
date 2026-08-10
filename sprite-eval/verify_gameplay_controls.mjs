#!/usr/bin/env node
import crypto from "node:crypto";
import fs from "node:fs";

const [wasmPath, snapshotPath, reportPath] = process.argv.slice(2);
if (!wasmPath || !snapshotPath || !reportPath) {
  throw new Error("usage: verify_gameplay_controls.mjs core.wasm snapshot.sna report.json");
}

const wasm = fs.readFileSync(wasmPath);
const snapshot = fs.readFileSync(snapshotPath);
const { instance } = await WebAssembly.instantiate(wasm);
const core = instance.exports;
const memory = new Uint8Array(core.memory.buffer);
const registers = new Uint16Array(core.memory.buffer, core.REGISTERS, 12);
const page = (bank) => core.MACHINE_MEMORY + bank * 0x4000;
const load = (bank, offset) => memory.set(snapshot.subarray(offset, offset + 0x4000), page(bank));

core.setMachineType(128);
memory.fill(0, page(8), page(10));
load(5, 27);
load(2, 27 + 0x4000);
load(0, 27 + 0x8000);
let offset = 49183;
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

const fixed = (address) => page(2) + address - 0x8000;
const u8 = (address) => memory[fixed(address)];
const u16 = (address) => u8(address) | (u8(address + 1) << 8);
const run = (refreshes) => {
  for (let i = 0; i < refreshes; ++i) {
    const status = core.runFrame();
    if (status !== 0) throw new Error(`emulator status ${status}`);
  }
};

run(40);
const initialPosition = u8(0x9f0b);
const initialBuddy = u8(0x9f12);

core.keyDown(5, 1); // P
run(80);
core.keyUp(5, 1);
const rightPosition = u8(0x9f0b);
const rightBuddy = u8(0x9f12);

core.keyDown(7, 1); // SPACE
run(12);
core.keyUp(7, 1);
const fireAction = u8(0x9f10);
const fireDirection = u8(0x9f11);
const firePosition = u8(0x9f0b);

run(20);
const releasedAction = u8(0x9f10);
const report = {
  passed:
    rightPosition > initialPosition &&
    rightBuddy > initialBuddy &&
    rightBuddy < rightPosition &&
    fireAction === 1 &&
    fireDirection === 0 &&
    firePosition === rightPosition &&
    releasedAction === 0 &&
    u8(0x9f07) === 0,
  snapshot: {
    bytes: snapshot.length,
    sha256: crypto.createHash("sha256").update(snapshot).digest("hex"),
  },
  controls: {
    left: "O",
    right: "P",
    fire: "SPACE",
    initialPosition,
    rightPosition,
    initialBuddy,
    rightBuddy,
    fireAction,
    fireDirection,
    firePosition,
    releasedAction,
  },
  timing: {
    deadlineMisses: u8(0x9f07),
    renderInterruptMax: u8(0x9f08),
    presentations: u16(0x9f04),
  },
};
fs.writeFileSync(reportPath, `${JSON.stringify(report, null, 2)}\n`);
process.stdout.write(`${JSON.stringify(report, null, 2)}\n`);
if (!report.passed) process.exitCode = 1;
