import fs from 'node:fs';

const snaPath = process.argv[2];
const count = Number(process.argv[3]);
const holdFrames = Number(process.argv[4] ?? 10);
if (!snaPath || !count || !holdFrames) throw new Error('usage: node run_full_speccy_capture.mjs reel.sna frameCount [holdFrames]');
const wasm = fs.readFileSync(new URL('jsspeccy-core.wasm', import.meta.url));
const { instance } = await WebAssembly.instantiate(wasm);
const core = instance.exports;
const memory = new Uint8Array(core.memory.buffer);
const regs = new Uint16Array(core.memory.buffer, core.REGISTERS, 12);
const sna = fs.readFileSync(snaPath);
core.setMachineType(128);
const loadPage = (n, off) => memory.set(sna.subarray(off, off+0x4000), core.MACHINE_MEMORY+n*0x4000);
memory.set(fs.readFileSync(new URL('rom-128-0.bin', import.meta.url)), core.MACHINE_MEMORY+8*0x4000);
memory.set(fs.readFileSync(new URL('rom-128-1.bin', import.meta.url)), core.MACHINE_MEMORY+9*0x4000);
loadPage(5,27); loadPage(2,27+0x4000); loadPage(0,27+0x8000);
let ptr=49183;
for (const n of [1,3,4,6,7]) { loadPage(n,ptr); ptr+=0x4000; }
regs.fill(0); regs[10]=0x7ff0;
core.setPC(0x5b00); core.setIFF1(1); core.setIFF2(1); core.setIM(1);
core.setHalted(false); core.writePort(0xfe,0); core.writePort(0x7ffd,0); core.setTStates(0);
const palette=[[0,0,0],[32,48,192],[192,64,16],[192,64,192],[64,176,16],[80,192,176],[224,192,16],[192,192,192],[0,0,0],[48,64,255],[255,64,48],[255,112,240],[80,224,16],[80,224,255],[255,232,80],[255,255,255]];
function rgbFrame(frame) {
  const out=Buffer.allocUnsafe(320*240*3); let i=0,o=0;
  const pixel=index=>{const c=palette[index&15];out[o++]=c[0];out[o++]=c[1];out[o++]=c[2];};
  for(let y=0;y<24;y++)for(let x=0;x<160;x++){const c=frame[i++];pixel(c);pixel(c);}
  for(let y=0;y<192;y++){
    for(let x=0;x<16;x++){const c=frame[i++];pixel(c);pixel(c);}
    for(let x=0;x<32;x++){let bits=frame[i++],attr=frame[i++];const ink=((attr&0x40)>>3)|(attr&7),paper=(attr&0x78)>>3;for(let b=0;b<8;b++){pixel(bits&0x80?ink:paper);bits<<=1;}}
    for(let x=0;x<16;x++){const c=frame[i++];pixel(c);pixel(c);}
  }
  for(let y=0;y<24;y++)for(let x=0;x<160;x++){const c=frame[i++];pixel(c);pixel(c);}
  return out;
}
for(let n=0;n<count*holdFrames;n++){
  const status=core.runFrame(); if(status!==0)throw new Error(`core status ${status}`);
  process.stdout.write(rgbFrame(memory.subarray(core.FRAME_BUFFER,core.FRAME_BUFFER+0x6600)));
}
