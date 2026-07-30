#!/usr/bin/env python3
from __future__ import annotations
import argparse, importlib.util, json, re, shutil, subprocess
from pathlib import Path

RENDERER_OFFSET_BANK5=0x1D20
EVENT_RUNS_OFFSET_BANK5=0x2C00

def bank_offset(bank:int)->int:
    if bank==5: return 27
    if bank==2: return 27+0x4000
    if bank==0: return 27+0x8000
    return 49183+[1,3,4,6,7].index(bank)*0x4000

def inject(sna:bytes, bank:int, offset:int, data:bytes)->bytes:
    out=bytearray(sna); pos=bank_offset(bank)+offset; out[pos:pos+len(data)]=data; return bytes(out)

def load(path:Path):
    spec=importlib.util.spec_from_file_location('row_fill_patch',path)
    mod=importlib.util.module_from_spec(spec); assert spec.loader; spec.loader.exec_module(mod); return mod

def normalize(path:Path):
    text=path.read_text(); text=re.sub(r'(?m)^\s+(\.[A-Za-z_][A-Za-z0-9_]*:)\s*$',r'\1',text); path.write_text(text)

def asm(sjasm:Path, src:Path, out:Path)->bytes:
    subprocess.run([str(sjasm),f'--raw={out}',src.name],cwd=src.parent,check=True)
    return out.read_bytes()

def main():
    ap=argparse.ArgumentParser(); ap.add_argument('--out',type=Path,required=True); ap.add_argument('--work',type=Path,required=True); ap.add_argument('--patch',type=Path,required=True); ap.add_argument('--sjasmplus',type=Path,required=True)
    a=ap.parse_args(); a.out.mkdir(parents=True,exist_ok=True); p=load(a.patch)
    base=(a.out/'u-w1-fill.sna').read_bytes(); shutil.copy2(a.out/'u-w1-fill.sna',a.out/'r-baseline.sna')
    renderer0=(a.work/'renderer-both.asm').read_text()
    specs=['row-ldir','row-ldi32','row-vertical-indexed','row-vertical-exx','row-vertical-exx-table']
    manifest={'baseline':'u-w1-fill','variants':{'r-baseline':{'snapshot_bytes':len(base)}}}; built=['r-baseline']
    for mode in specs:
        label='r-'+mode
        try:
            text=p.patch_renderer(renderer0,mode)
            src=a.work/f'renderer-{label}.asm'; src.write_text(text); normalize(src)
            rb=asm(a.sjasmplus,src,a.out/f'renderer-{label}.bin')
            gap=EVENT_RUNS_OFFSET_BANK5-(RENDERER_OFFSET_BANK5+len(rb))
            if gap<0: raise RuntimeError(f'renderer overlap {-gap} bytes')
            sna=inject(base,5,RENDERER_OFFSET_BANK5,rb); (a.out/f'{label}.sna').write_bytes(sna)
            manifest['variants'][label]={'renderer_bytes':len(rb),'renderer_gap_remaining':gap,'snapshot_bytes':len(sna),'mode':mode}
            built.append(label)
        except Exception as e:
            manifest['variants'][label]={'skipped':True,'error':str(e),'mode':mode}
    (a.out/'row-fill-build-manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
    (a.out/'row-fill-labels.txt').write_text(' '.join(built)+'\n')
    print(json.dumps(manifest,indent=2)); print('LABELS',' '.join(built))

if __name__=='__main__': main()
