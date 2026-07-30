#!/usr/bin/env python3
from __future__ import annotations
import argparse, importlib.util, json, re, shutil, subprocess
from pathlib import Path

VM_OFFSET_BANK2 = 0
RENDERER_OFFSET_BANK5 = 0x1D20
EVENT_RUNS_OFFSET_BANK5 = 0x2C00


def bank_offset(bank: int) -> int:
    if bank == 5: return 27
    if bank == 2: return 27 + 0x4000
    if bank == 0: return 27 + 0x8000
    return 49183 + [1,3,4,6,7].index(bank) * 0x4000


def inject(sna: bytes, bank: int, offset: int, data: bytes) -> bytes:
    out = bytearray(sna); pos = bank_offset(bank) + offset
    out[pos:pos+len(data)] = data
    return bytes(out)


def load(path: Path):
    spec=importlib.util.spec_from_file_location('unrolled_perf_patch', path)
    mod=importlib.util.module_from_spec(spec); assert spec.loader; spec.loader.exec_module(mod); return mod


def normalize(path: Path):
    text=path.read_text(); text=re.sub(r'(?m)^\s+(\.[A-Za-z_][A-Za-z0-9_]*:)\s*$', r'\1', text); path.write_text(text)


def asm(sjasm: Path, src: Path, out: Path) -> bytes:
    subprocess.run([str(sjasm), f'--raw={out}', src.name], cwd=src.parent, check=True)
    return out.read_bytes()


def main():
    ap=argparse.ArgumentParser(); ap.add_argument('--out',type=Path,required=True); ap.add_argument('--work',type=Path,required=True); ap.add_argument('--patch',type=Path,required=True); ap.add_argument('--sjasmplus',type=Path,required=True)
    a=ap.parse_args(); a.out.mkdir(parents=True,exist_ok=True); p=load(a.patch)
    base=(a.out/'both.sna').read_bytes(); shutil.copy2(a.out/'both.sna',a.out/'u-baseline.sna')
    vm0=(a.work/'vm-both.asm').read_text(); r0=(a.work/'renderer-both.asm').read_text()
    specs={
      'u-w1-loop': ({'w1':'loop'}, {}),
      'u-w1-unrolled': ({'w1':'unrolled'}, {}),
      'u-w2': ({'short':(2,)}, {}),
      'u-w3': ({'short':(3,)}, {}),
      'u-w4': ({'short':(4,)}, {}),
      'u-w8': ({'hot':(8,)}, {}),
      'u-w16': ({'hot':(16,)}, {}),
      'u-w32': ({'hot':(32,)}, {}),
      'u-fill-cell8': ({}, {'fill_cell8':True}),
      'u-w1-fill': ({'w1':'unrolled'}, {'fill_cell8':True}),
    }
    manifest={'variants':{'u-baseline':{'snapshot_bytes':len(base)}}}; built=['u-baseline']
    for label,(vmkw,rkw) in specs.items():
        try:
            vms=p.patch_vm(vm0,**vmkw); rs=p.patch_renderer(r0,**rkw)
            vmp=a.work/f'vm-{label}.asm'; rp=a.work/f'renderer-{label}.asm'; vmp.write_text(vms); rp.write_text(rs); normalize(vmp); normalize(rp)
            vb=asm(a.sjasmplus,vmp,a.out/f'vm-{label}.bin'); rb=asm(a.sjasmplus,rp,a.out/f'renderer-{label}.bin')
            gap=EVENT_RUNS_OFFSET_BANK5-(RENDERER_OFFSET_BANK5+len(rb))
            if gap<0: raise RuntimeError(f'renderer overlap {-gap} bytes')
            sna=inject(base,2,0,vb); sna=inject(sna,5,RENDERER_OFFSET_BANK5,rb); (a.out/f'{label}.sna').write_bytes(sna)
            manifest['variants'][label]={'vm_bytes':len(vb),'renderer_bytes':len(rb),'renderer_gap_remaining':gap,'snapshot_bytes':len(sna),'vm_options':vmkw,'renderer_options':rkw}
            built.append(label)
        except Exception as e:
            manifest['variants'][label]={'skipped':True,'error':str(e),'vm_options':vmkw,'renderer_options':rkw}
    (a.out/'unrolled-build-manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
    (a.out/'unrolled-labels.txt').write_text(' '.join(built)+'\n')
    print(json.dumps(manifest,indent=2)); print('LABELS',' '.join(built))

if __name__=='__main__': main()
