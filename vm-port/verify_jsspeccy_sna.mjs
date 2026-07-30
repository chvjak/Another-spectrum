#!/usr/bin/env node
import fs from 'node:fs';
import path from 'node:path';
import crypto from 'node:crypto';

const [wasmPath, romDir, originalPath, outDir] = process.argv.slice(2);
if (!wasmPath || !romDir || !originalPath || !outDir) {
  throw new Error('usage: verify_jsspeccy_sna.mjs core.wasm romDir input.sna outDir');
}
fs.mkdirSync(outDir, { recursive: true });

function parseSNAFile(data) {
  let mode128 = false;
  const len = data.byteLength;
  let sna;
  switch (len) {
    case 131103:
    case 147487:
      mode128 = true;
      // fall through
    case 49179: {
      sna = new DataView(data.buffer, data.byteOffset, mode128 ? 49182 : len);
      const snapshot = {
        model: mode128 ? 128 : 48,
        registers: {},
        ulaState: {},
        memoryPages: {
          5: new Uint8Array(data.buffer, data.byteOffset + 27, 0x4000),
          2: new Uint8Array(data.buffer, data.byteOffset + 27 + 0x4000, 0x4000),
        },
        tstates: 0,
      };
      if (!mode128) throw new Error('48K SNA not needed for this verification');
      const page = sna.getUint8(49181) & 7;
      snapshot.memoryPages[page] = new Uint8Array(data.buffer, data.byteOffset + 27 + 0x8000, 0x4000);
      for (let i = 0, ptr = 49183; i < 8; i++) {
        if (typeof snapshot.memoryPages[i] === 'undefined') {
          snapshot.memoryPages[i] = new Uint8Array(data.buffer, data.byteOffset + ptr, 0x4000);
          ptr += 0x4000;
        }
      }
      snapshot.registers.IR = (sna.getUint8(0) << 8) | sna.getUint8(20);
      snapshot.registers.HL_ = sna.getUint16(1, true);
      snapshot.registers.DE_ = sna.getUint16(3, true);
      snapshot.registers.BC_ = sna.getUint16(5, true);
      snapshot.registers.AF_ = sna.getUint16(7, true);
      snapshot.registers.HL = sna.getUint16(9, true);
      snapshot.registers.DE = sna.getUint16(11, true);
      snapshot.registers.BC = sna.getUint16(13, true);
      snapshot.registers.IY = sna.getUint16(15, true);
      snapshot.registers.IX = sna.getUint16(17, true);
      snapshot.registers.iff1 = snapshot.registers.iff2 = (sna.getUint8(19) & 0x04) >> 2;
      snapshot.registers.AF = sna.getUint16(21, true);
      snapshot.registers.SP = sna.getUint16(23, true);
      snapshot.registers.PC = sna.getUint16(49179, true);
      snapshot.ulaState.pagingFlags = sna.getUint8(49181);
      snapshot.registers.im = sna.getUint8(25);
      snapshot.ulaState.borderColour = sna.getUint8(26);
      return snapshot;
    }
    default:
      throw new Error(`Cannot handle SNA snapshots of length ${len}`);
  }
}

const palette = [
  [0x00,0x00,0x00],[0x20,0x30,0xc0],[0xc0,0x40,0x10],[0xc0,0x40,0xc0],
  [0x40,0xb0,0x10],[0x50,0xc0,0xb0],[0xe0,0xc0,0x10],[0xc0,0xc0,0xc0],
  [0x00,0x00,0x00],[0x30,0x40,0xff],[0xff,0x40,0x30],[0xff,0x70,0xf0],
  [0x50,0xe0,0x10],[0x50,0xe0,0xff],[0xff,0xe8,0x50],[0xff,0xff,0xff],
];

function decodeFrame(frameBytes) {
  const rgb = Buffer.alloc(320 * 240 * 3);
  let ptr = 0;
  let out = 0;
  let nonBlack = 0;
  const emit = idx => {
    const [r,g,b] = palette[idx & 15];
    rgb[out++] = r; rgb[out++] = g; rgb[out++] = b;
    if (r || g || b) nonBlack++;
  };
  for (let y=0; y<24; y++) for (let x=0; x<160; x++) { const c=frameBytes[ptr++]; emit(c); emit(c); }
  for (let y=0; y<192; y++) {
    for (let x=0; x<16; x++) { const c=frameBytes[ptr++]; emit(c); emit(c); }
    for (let x=0; x<32; x++) {
      let bitmap = frameBytes[ptr++];
      const attr = frameBytes[ptr++];
      const ink = ((attr & 0x40) >> 3) | (attr & 7);
      const paper = (attr & 0x78) >> 3;
      for (let i=0; i<8; i++) { emit(bitmap & 0x80 ? ink : paper); bitmap = (bitmap << 1) & 0xff; }
    }
    for (let x=0; x<16; x++) { const c=frameBytes[ptr++]; emit(c); emit(c); }
  }
  for (let y=0; y<24; y++) for (let x=0; x<160; x++) { const c=frameBytes[ptr++]; emit(c); emit(c); }
  if (ptr !== 0x6600 || out !== rgb.length) throw new Error(`frame decode mismatch ptr=${ptr} out=${out}`);
  return { rgb, nonBlack };
}

function writePPM(filePath, rgb) {
  fs.writeFileSync(filePath, Buffer.concat([Buffer.from('P6\n320 240\n255\n'), rgb]));
}

async function setup(snapshot) {
  const wasm = fs.readFileSync(wasmPath);
  const { instance } = await WebAssembly.instantiate(wasm);
  const core = instance.exports;
  const memoryData = new Uint8Array(core.memory.buffer);
  const regs = new Uint16Array(core.memory.buffer, core.REGISTERS, 12);
  const pageAddr = page => core.MACHINE_MEMORY + page * 0x4000;
  core.setMachineType(snapshot.model);
  for (const [name, page] of [['128-0.rom',8],['128-1.rom',9],['48.rom',10]]) {
    const romPath = path.join(romDir, name);
    if (fs.existsSync(romPath)) memoryData.set(fs.readFileSync(romPath), pageAddr(page));
  }
  for (const [page, bytes] of Object.entries(snapshot.memoryPages)) memoryData.set(bytes, pageAddr(Number(page)));
  ['AF','BC','DE','HL','AF_','BC_','DE_','HL_','IX','IY','SP','IR'].forEach((r,i) => { regs[i] = snapshot.registers[r]; });
  core.setPC(snapshot.registers.PC);
  core.setIFF1(snapshot.registers.iff1);
  core.setIFF2(snapshot.registers.iff2);
  core.setIM(snapshot.registers.im);
  core.setHalted(!!snapshot.halted);
  core.writePort(0x00fe, snapshot.ulaState.borderColour);
  core.writePort(0x7ffd, snapshot.ulaState.pagingFlags);
  core.setTStates(snapshot.tstates);
  core.setAudioSamplesPerFrame(0);
  return { core, memoryData, pageAddr };
}

async function runVariant(label, snaBytes, maxFrames=8300) {
  const snapshot = parseSNAFile(snaBytes);
  const { core, memoryData, pageAddr } = await setup(snapshot);
  const fixed2 = address => pageAddr(2) + address - 0x8000;
  const u8 = address => memoryData[fixed2(address)];
  const u16 = address => u8(address) | (u8(address+1) << 8);
  const frameData = memoryData.subarray(core.FRAME_BUFFER, core.FRAME_BUFFER + 0x6600);
  const captures = new Set([1,2,5,10,25,50,100,250,500,1000,2000,4000,8000]);
  let firstNonBlack = null;
  let maxNonBlack = 0;
  let firstPresentation = null;
  let status = 0;
  let frame = 0;
  const samples = [];
  for (frame=1; frame<=maxFrames && u8(0x9307)===0; frame++) {
    status = core.runFrame();
    if (status !== 0) break;
    const decoded = decodeFrame(frameData);
    if (decoded.nonBlack > 0 && firstNonBlack === null) firstNonBlack = frame;
    maxNonBlack = Math.max(maxNonBlack, decoded.nonBlack);
    const presentation = u16(0x9308);
    if (presentation > 0 && firstPresentation === null) firstPresentation = frame;
    if (captures.has(frame) || firstNonBlack === frame || firstPresentation === frame) {
      const name = `${label}-frame-${String(frame).padStart(4,'0')}.ppm`;
      writePPM(path.join(outDir, name), decoded.rgb);
      samples.push({ frame, non_black_pixels: decoded.nonBlack, presentation, file: name });
    }
  }
  const hostFrames = frame - 1;
  return {
    label,
    header: {
      model: snapshot.model,
      pc: snapshot.registers.PC,
      sp: snapshot.registers.SP,
      iff1: snapshot.registers.iff1,
      iff2: snapshot.registers.iff2,
      im: snapshot.registers.im,
      i: snapshot.registers.IR >> 8,
      paging_flags: snapshot.ulaState.pagingFlags,
      display_bank: (snapshot.ulaState.pagingFlags & 8) ? 7 : 5,
    },
    status,
    host_frames: hostFrames,
    done: u8(0x9307),
    vm_tick: u16(0x9300),
    instruction_count: u16(0x9302),
    trace_hash: u16(0x9304),
    error_opcode: u8(0x9306),
    rendered_presentations: u16(0x9308),
    first_non_black_frame: firstNonBlack,
    first_presentation_frame: firstPresentation,
    max_non_black_pixels: maxNonBlack,
    samples,
  };
}

const original = fs.readFileSync(originalPath);
const iffOff = Buffer.from(original);
iffOff[19] = 0;
const loaderSafe = Buffer.from(original);
loaderSafe[19] = 0;
loaderSafe[25] = 1;
fs.writeFileSync(path.join(outDir, 'cost-4p5-ay-iff-off.sna'), iffOff);
fs.writeFileSync(path.join(outDir, 'cost-4p5-ay-jsspeccy-safe.sna'), loaderSafe);

const results = {
  emulator: 'JSSpeccy 3.2.0 parseSNAFile + worker loadSnapshot semantics + jsspeccy-core.wasm',
  original_sha256: crypto.createHash('sha256').update(original).digest('hex'),
  variants: [],
};
for (const [label, bytes] of [['original', original], ['iff-off', iffOff], ['loader-safe', loaderSafe]]) {
  results.variants.push(await runVariant(label, bytes));
}
results.black_original = results.variants[0].max_non_black_pixels === 0;
results.loader_safe_passed = results.variants[2].done === 1 && results.variants[2].rendered_presentations === 268 && results.variants[2].status === 0;
fs.writeFileSync(path.join(outDir, 'jsspeccy-sna-verification.json'), JSON.stringify(results, null, 2) + '\n');
console.log(JSON.stringify(results, null, 2));
if (!results.loader_safe_passed) process.exitCode = 1;
