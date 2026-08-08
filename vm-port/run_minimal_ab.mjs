import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
const here = path.dirname(fileURLToPath(import.meta.url));

const [wasmPath, buildDir] = process.argv.slice(2);
if (!wasmPath || !buildDir) throw new Error('usage: node run_minimal_ab.mjs core.wasm build-dir');
const wasm = fs.readFileSync(wasmPath);

async function run(label) {
  const sna = fs.readFileSync(path.join(buildDir, `${label}.sna`));
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
  for (const bank of [1,3,4,6,7]) { loadPage(bank, sourceOffset); sourceOffset += 0x4000; }
  regs.fill(0); regs[10] = 0xBFF0;
  core.setPC(0x8000); core.setIFF1(0); core.setIFF2(0); core.setIM(1); core.setHalted(false);
  core.writePort(0x00FE, 0); core.writePort(0x7FFD, 0); core.setTStates(0);
  const fixed = a => pageAddress(2) + a - 0x8000;
  const u8 = a => memory[fixed(a)];
  const u16 = a => u8(a) | (u8(a+1)<<8);
  const b5u8 = a => memory[pageAddress(5)+a-0x4000];
  const b5u16 = a => b5u8(a) | (b5u8(a+1)<<8);
  let hostFrames=0;
  while (u8(0x9307)===0 && hostFrames<100000) {
    const status=core.runFrame();
    if(status!==0) throw new Error(`${label}: core status ${status}`);
    hostFrames++;
  }
  return {
    label, done:u8(0x9307), host_frames:hostFrames, vm_tick:u16(0x9300),
    instruction_count:u16(0x9302), trace_hash:u16(0x9304), error_opcode:u8(0x9306),
    sampled_frames:u16(0x9308), decoded_primitives:b5u16(0x7283), renderer_error:b5u8(0x7282),
    renderer_error_root:b5u16(0x72a2), renderer_error_shape:b5u16(0x729d), renderer_error_code:b5u8(0x729f),
  };
}
const baseline=await run('baseline');
const st=await run('st');
const report={
  passed: baseline.done===1 && st.done===1 && baseline.error_opcode===0 && st.error_opcode===0 && baseline.renderer_error===0 && st.renderer_error===0,
  trace_equal: baseline.vm_tick===st.vm_tick && baseline.instruction_count===st.instruction_count && baseline.trace_hash===st.trace_hash,
  primitives_equal: baseline.decoded_primitives===st.decoded_primitives,
  baseline, st,
  whole_run_speedup: baseline.host_frames/st.host_frames,
  whole_run_saved_percent:(1-st.host_frames/baseline.host_frames)*100,
};
fs.writeFileSync(path.join(buildDir,'minimal-ab-result.json'),JSON.stringify(report,null,2)+'\n');
console.log(JSON.stringify(report,null,2));
if(!report.passed || !report.trace_equal || !report.primitives_equal) process.exitCode=1;
