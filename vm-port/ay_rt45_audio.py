#!/usr/bin/env python3
"""Render the exact AY schedule used by cost-4p5-ay, including startup silence."""
from __future__ import annotations
import argparse, json, struct, wave
from pathlib import Path
import numpy as np
from scipy.signal import butter, sosfilt

FPS=50; TICKS=8226; START_TICK=20; UPDATES=len(range(START_TICK,TICKS,2)); SR=44100; SAMPLES_PER_TICK=SR//FPS; AY_CLOCK=1773400.0
VOL=np.array([0.0,.0046,.0065,.0092,.0130,.0184,.0260,.0368,.0520,.0735,.104,.147,.208,.294,.416,.588],dtype=np.float32)

def parse(path:Path)->np.ndarray:
    raw=path.read_bytes()
    if raw[:4]!=b'AY50': raise RuntimeError('not AY50')
    count=struct.unpack_from('<H',raw,4)[0]
    if count<TICKS: raise RuntimeError(f'{count} ticks < {TICKS}')
    pos=6; cur=np.zeros(14,dtype=np.uint8); cur[7]=0x3F; out=np.empty((TICKS,14),dtype=np.uint8)
    for tick in range(count):
        mask=struct.unpack_from('<H',raw,pos)[0]; pos+=2
        for reg in range(14):
            if mask&(1<<reg): cur[reg]=raw[pos]; pos+=1
        if tick<TICKS: out[tick]=cur
    if pos!=len(raw): raise RuntimeError(f'parse {pos} != {len(raw)}')
    return out

def player_schedule(source:np.ndarray)->np.ndarray:
    out=np.zeros((TICKS,14),dtype=np.uint8); out[:,7]=0x3F
    for tick in range(START_TICK,TICKS):
        source_tick=START_TICK+((tick-START_TICK)//2)*2
        out[tick]=source[source_tick]
    return out

def synth(regs:np.ndarray)->np.ndarray:
    total=TICKS*SAMPLES_PER_TICK; channels=np.zeros((3,total),dtype=np.float32)
    phases=[0.0,0.0,0.0]; rng=np.random.default_rng(0xA17E); idx=np.arange(SAMPLES_PER_TICK)
    for tick,row in enumerate(regs):
        sl=slice(tick*SAMPLES_PER_TICK,(tick+1)*SAMPLES_PER_TICK)
        npd=max(1,int(row[6]&31)); nf=AY_CLOCK/(16*npd); step=max(1,int(round(SR/nf)))
        vals=rng.choice(np.array([-1.0,1.0],dtype=np.float32),size=(SAMPLES_PER_TICK+step-1)//step)
        noise=np.repeat(vals,step)[:SAMPLES_PER_TICK]
        for c in range(3):
            pd=max(1,int(row[c*2])|((int(row[c*2+1])&15)<<8)); tf=AY_CLOCK/(16*pd)
            ph=(phases[c]+idx*tf/SR)%1.0; tone=np.where(ph<.5,1.0,-1.0).astype(np.float32)
            phases[c]=float((phases[c]+SAMPLES_PER_TICK*tf/SR)%1.0)
            ten=((int(row[7])>>c)&1)==0; nen=((int(row[7])>>(c+3))&1)==0
            if ten and nen: gate=np.where((tone>0)&(noise>0),1.0,-1.0).astype(np.float32)
            elif ten: gate=tone
            elif nen: gate=noise
            else: gate=np.zeros(SAMPLES_PER_TICK,dtype=np.float32)
            channels[c,sl]=gate*VOL[int(row[8+c])&15]
    mixed=channels.sum(axis=0); room=mixed.astype(np.float64)
    for ms,gain in ((46,.10),(83,.055)):
        delay=int(SR*ms/1000); room[delay:]+=gain*mixed[:-delay]
    shaped=np.tanh(room*1.12)
    filtered=sosfilt(butter(2,[35,8400],btype='bandpass',fs=SR,output='sos'),shaped)
    peak=float(np.max(np.abs(filtered)))
    if peak>1e-9: filtered*=.84/peak
    return (filtered*.70).astype(np.float32)

def main():
    ap=argparse.ArgumentParser(); ap.add_argument('ay50',type=Path); ap.add_argument('output',type=Path); ap.add_argument('--manifest',type=Path); a=ap.parse_args()
    audio=synth(player_schedule(parse(a.ay50))); a.output.parent.mkdir(parents=True,exist_ok=True)
    pcm=np.int16(np.clip(audio,-1,1)*32767)
    with wave.open(str(a.output),'wb') as f:
        f.setnchannels(1); f.setsampwidth(2); f.setframerate(SR); f.writeframes(pcm.tobytes())
    info={'source':str(a.ay50),'ticks_50hz':TICKS,'duration_seconds':TICKS/FPS,'startup_silence_ticks':START_TICK,'source_start_tick':START_TICK,'register_updates':UPDATES,'register_update_rate_hz':25,'sample_rate':SR,'samples':len(audio),'wav_bytes':a.output.stat().st_size,'render':'software synthesis of the exact startup-delayed even-tick register schedule played by the resident AY ISR'}
    if a.manifest: a.manifest.write_text(json.dumps(info,indent=2)+'\n')
    print(json.dumps(info,indent=2))
if __name__=='__main__': main()
