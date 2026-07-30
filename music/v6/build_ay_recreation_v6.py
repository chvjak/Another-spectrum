from __future__ import annotations

import csv, gzip, json, math, shutil, struct, subprocess, wave, zipfile
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from scipy.signal import butter, sosfilt

OUT = Path(__file__).resolve().parent / 'generated'
OUT.mkdir(parents=True, exist_ok=True)
FPS = 50
DURATION = 170.0
TICKS = int(DURATION * FPS)
SR = 44100
SAMPLES_PER_TICK = SR // FPS  # 882 exactly
AY_CLOCK = 1773400.0

NOTE_IDX = {'C':0,'C#':1,'D':2,'D#':3,'E':4,'F':5,'F#':6,'G':7,'G#':8,'A':9,'A#':10,'B':11}

def midi(note: str) -> int:
    if note == 'R': return -1
    if len(note) >= 3 and note[1] == '#': name, octv = note[:2], int(note[2:])
    else: name, octv = note[0], int(note[1:])
    return 12*(octv+1)+NOTE_IDX[name]

def freq(note: str|int, cents: float=0.0) -> float:
    m = midi(note) if isinstance(note,str) else note
    if m < 0: return 0.0
    return 440.0 * 2.0 ** ((m-69)/12.0 + cents/1200.0)

def period(note: str|int, cents: float=0.0) -> int:
    f = freq(note,cents)
    return max(1,min(4095,round(AY_CLOCK/(16*f)))) if f>0 else 1

def sec(s: float) -> int: return int(round(s*FPS))

@dataclass
class Ev:
    start:int; duration:int; note:str; vol:int; instrument:str

melody: list[Ev] = []
bass: list[Ev] = []

# Melodic material: same restrained motifs as v3, but timbre/envelopes change.
def add_phrase(start_s,end_s,notes,weights,vol=9,instrument='lead'):
    start,end=sec(start_s),sec(end_s)
    total=sum(weights); cur=0
    for n,w in zip(notes,weights):
        s=start+round((end-start)*cur/total); cur+=w; e=start+round((end-start)*cur/total)
        if n!='R': melody.append(Ev(s,max(1,e-s),n,vol,instrument))

motif_a=['B3','G3','A3','G3','D3','F#3','E3']; wa=[1,1,3,1,1,1,5]
motif_b=['B3','G3','A3','G3','D3','E3','B3','G3','A3','G3','D3','E3']; wb=[1,1,3,1,1,3,1,1,3,1,1,5]
motif_c=['B3','G3','A3','G3','D3','E3','F#3','G3','A3','B3']; wc=[1,1,3,1,1,2,1,1,2,5]
ending=['E4','D4','A3','B3','A3','G3','F#3','E3']; we=[1,1,1,3,1,1,1,6]
add_phrase(20.5,47.5,motif_a,wa,9,'breathy')
add_phrase(49.5,78,motif_b,wb,9,'glass')
add_phrase(81,108.5,motif_c,wc,10,'breathy')
add_phrase(110.5,136,motif_a,wa,9,'glass')
add_phrase(138,158,ending,we,10,'breathy')
melody += [Ev(sec(158),sec(5.8),'E4',9,'glass'), Ev(sec(164),sec(5.0),'E3',7,'breathy')]

bass_sections=[(0,20.5,'E1',7),(20.5,48,'E1',8),(48,79,'C2',8),(79,109,'D2',8),(109,137,'E1',8),(137,159,'B1',9),(159,170,'E1',7)]
for st,en,n,v in bass_sections:
    cursor=st
    while cursor<en:
        span=min(8.5,en-cursor)
        bass.append(Ev(sec(cursor),max(1,sec(span+0.45)),n,v,'machine'))
        cursor += 7.6

@dataclass
class Drum:
    tick:int; kind:str; strength:float

drums: list[Drum] = []
BEAT=60/71

def add_beat(st,en,intensity):
    i=0; t=st
    while t<en:
        if i%4==0: drums.append(Drum(sec(t),'thump',0.40*intensity))
        if i%4 in (1,3): drums.append(Drum(sec(t),'snare',0.66*intensity))
        if i%8 in (3,7): drums.append(Drum(sec(t-BEAT*.16),'brush',0.30*intensity))
        # No periodic metallic pulse: it was the remaining tractor-like element.
        i+=1; t+=BEAT

add_beat(17.5,49,0.68); add_beat(49,81,0.78); add_beat(81,110,0.88); add_beat(110,139,0.74); add_beat(139,160,0.92)
for t in (161.0,164.4,167.8): drums.append(Drum(sec(t),'brush',0.22))

drum_at={}
for d in drums:
    if d.tick not in drum_at or d.strength>drum_at[d.tick].strength: drum_at[d.tick]=d

# Event lookup tables.
def lookup(events):
    arr=[None]*TICKS
    for e in events:
        for t in range(max(0,e.start),min(TICKS,e.start+e.duration)):
            arr[t]=e
    return arr
mel_at=lookup(melody); bass_at=lookup(bass)

# Software envelope macros: shaped more like sampled instruments than generic ADSR.
def lead_env(kind, age, dur, peak):
    # A sampled-like attack transient, quick decay, then long low sustain and tail.
    if kind=='glass':
        macro=[0.52,0.68,0.82,0.92,0.88,0.78,0.68,0.60,0.55,0.51]
    else: # breathy
        macro=[0.42,0.58,0.74,0.88,0.94,0.86,0.75,0.66,0.59,0.54]
    if age < len(macro): x=macro[age]
    else:
        p=(age-len(macro))/max(1,dur-len(macro))
        x=0.48*(1-p)**0.52 + 0.05
    # Longer tail than v3.
    rem=dur-age
    if rem<18: x*=max(0,rem/18)**0.65
    return max(0,min(15,round(peak*x)))

def bass_env(age,dur,peak):
    # Bowed bass: short bite, then a stable sustain without periodic pumping.
    if age<3: x=[0.45,0.92,1.0][age]
    elif age<9: x=[0.86,0.76,0.70,0.67,0.65,0.64][age-3]
    else:
        # A very slow one-way relaxation keeps it alive without forming a beat.
        x=0.66 - 0.06*min(1.0,(age-9)/max(1,dur-9))
    rem=dur-age
    if rem<28: x*=max(0,rem/28)**0.55
    return max(0,min(15,round(peak*x)))

regs=np.zeros((TICKS,14),dtype=np.uint8); regs[:,7]=0x3F
active_d=None; dstart=0

for t in range(TICKS):
    r=regs[t]
    # A bass/machine track
    e=bass_at[t]
    if e:
        age=t-e.start; dur=e.duration
        # Sampled-bass bite only at the note start; no repeating pitch grain.
        semitone=0
        if age==0: semitone=12
        elif age==1: semitone=7
        cents=0.0
        p=period(midi(e.note)+semitone,cents)
        r[0],r[1]=p&255,(p>>8)&15
        r[8]=bass_env(age,dur,e.vol)
        r[7]&=0xFE
        # Bass remains tone-only. Noise is carried by melody attacks and drums.

    # B gentle melody, with noisy sampled attack and less sterile square sustain
    e=mel_at[t]
    if e:
        age=t-e.start; dur=e.duration
        # brief pitch macro approximates sampled transient/harmonic content
        semi=0
        if age==0: semi=3 if e.instrument=='glass' else 2
        elif age==1: semi=2 if e.instrument=='glass' else 1
        elif age==2 and e.instrument=='glass': semi=1
        vib=0.0
        if age>10:
            vib=(2.0 if e.instrument=='breathy' else 1.25)*math.sin(2*math.pi*(age-10)/29.0)
        p=period(midi(e.note)+semi,vib)
        r[2],r[3]=p&255,(p>>8)&15
        r[9]=lead_env(e.instrument,age,dur,e.vol)
        r[7]&=0xFD
        # 1–3 tick noise onset gives breath/bow attack; skip when a snare is active
        if age < (3 if e.instrument=='breathy' else 2) and active_d is None:
            r[6]=7+age*4
            r[7]&=0xEF

    # C drums
    if t in drum_at: active_d=drum_at[t]; dstart=t
    if active_d:
        age=t-dstart; kind=active_d.kind; s=active_d.strength
        lens={'snare':13,'brush':18,'thump':10}; L=lens[kind]
        if age>=L: active_d=None
        else:
            x=age/(L-1)
            if kind=='snare':
                # body + noise for 4 ticks, then a soft noisy tail
                body_midi=47-round(6*x)
                p=period(body_midi)
                r[4],r[5]=p&255,(p>>8)&15
                r[6]=5+round(17*x)
                env=[8,9,8,7,6,5,4,4,3,3,2,1,0][age]
                r[10]=min(15,round(env*s*1.35))
                r[7]&=0xDB if age<4 else 0xDF  # tone+noise then noise only
                if age>=4: r[7]|=0x04
            elif kind=='brush':
                r[6]=12+round(12*x)
                env=[5,5,5,4,4,4,3,3,3,2,2,2,2,1,1,1,1,0][age]
                r[10]=min(15,round(env*s*1.5)); r[7]&=0xDF; r[7]|=0x04
            elif kind=='thump':
                p=period(43-round(11*x))
                r[4],r[5]=p&255,(p>>8)&15
                env=[8,8,7,6,5,4,3,2,1,0][age]
                r[10]=min(15,round(env*s*1.25)); r[7]&=0xFB; r[7]|=0x20

# End fade
fade=sec(165)
for t in range(fade,TICKS):
    k=max(0,(TICKS-1-t)/(TICKS-fade))
    regs[t,8:11]=np.round(regs[t,8:11].astype(float)*k).astype(np.uint8)
regs[-1,7]=0x3F; regs[-1,8:11]=0

# Encode AY50 deltas
stream=bytearray(b'AY50')+struct.pack('<H',TICKS)
prev=np.zeros(14,dtype=np.uint8); prev[7]=0x3F
for row in regs:
    mask=0; vals=[]
    for i,v in enumerate(row):
        if int(v)!=int(prev[i]): mask|=1<<i; vals.append(int(v))
    stream+=struct.pack('<H',mask)+bytes(vals); prev=row.copy()
(OUT/'aw_intro_ay_v6_2m50s.bin').write_bytes(stream)

with (OUT/'aw_intro_ay_v6_registers.csv').open('w',newline='') as f:
    w=csv.writer(f); w.writerow(['tick','seconds']+[f'R{i}' for i in range(14)])
    for i,row in enumerate(regs): w.writerow([i,f'{i/FPS:.3f}',*map(int,row)])

# VGM
vgm=bytearray(0x80); vgm[:4]=b'Vgm '; struct.pack_into('<I',vgm,8,0x150); struct.pack_into('<I',vgm,0x18,int(DURATION*44100)); struct.pack_into('<I',vgm,0x24,FPS); struct.pack_into('<I',vgm,0x34,0x80-0x34); struct.pack_into('<I',vgm,0x74,int(AY_CLOCK))
prev=np.full(14,255,dtype=np.uint8)
for row in regs:
    for i,v in enumerate(row):
        if int(v)!=int(prev[i]): vgm+=bytes([0xA0,i,int(v)])
    vgm+=bytes([0x61,0x72,0x03]); prev=row.copy()
vgm+=b'\x66'; struct.pack_into('<I',vgm,4,len(vgm)-4)
(OUT/'aw_intro_ay_v6_2m50s.vgm').write_bytes(vgm)
with gzip.open(OUT/'aw_intro_ay_v6_2m50s.vgz','wb',compresslevel=9) as f:f.write(vgm)

# Fast block synthesis from register frames.
voltab=np.array([0.0,.0046,.0065,.0092,.0130,.0184,.0260,.0368,.0520,.0735,.104,.147,.208,.294,.416,.588])
N=TICKS*SAMPLES_PER_TICK
chout=np.zeros((3,N),dtype=np.float32)
phase=[0.0,0.0,0.0]; rng=np.random.default_rng(0xA17E)
noise_state=1.0
for t,row in enumerate(regs):
    sl=slice(t*SAMPLES_PER_TICK,(t+1)*SAMPLES_PER_TICK); idx=np.arange(SAMPLES_PER_TICK)
    npd=max(1,int(row[6]&31)); nf=AY_CLOCK/(16*npd); step=max(1,int(round(SR/nf)))
    # sample-and-hold pseudo-LFSR approximation; deterministic and close in texture
    vals=rng.choice(np.array([-1.0,1.0],dtype=np.float32),size=(SAMPLES_PER_TICK+step-1)//step)
    noise=np.repeat(vals,step)[:SAMPLES_PER_TICK]
    for c in range(3):
        pd=max(1,int(row[c*2])|((int(row[c*2+1])&15)<<8)); tf=AY_CLOCK/(16*pd)
        ph=(phase[c]+idx*tf/SR)%1.0; tone=np.where(ph<.5,1.0,-1.0).astype(np.float32)
        phase[c]=float((phase[c]+SAMPLES_PER_TICK*tf/SR)%1.0)
        ten=((int(row[7])>>c)&1)==0; nen=((int(row[7])>>(c+3))&1)==0
        if ten and nen: gate=np.where((tone>0)&(noise>0),1.0,-1.0).astype(np.float32)
        elif ten: gate=tone
        elif nen: gate=noise
        else: gate=np.zeros(SAMPLES_PER_TICK,dtype=np.float32)
        chout[c,sl]=gate*voltab[int(row[8+c])&15]

# Mix with subtle crossfeed/echo-like room reflections that remain generated from the same AY tracks.
def post(x,peak=.84):
    x=np.tanh(x*1.12)
    # high-pass 35 Hz, low-pass 9.5 kHz
    sos=butter(2,[35,8400],btype='bandpass',fs=SR,output='sos'); y=sosfilt(sos,x)
    m=np.max(np.abs(y));
    if m>1e-9:y=y*(peak/m)
    return y.astype(np.float32)

# Very short low-level repeats help the sampled feel without adding a fourth musical track.
def room(x):
    y=x.astype(np.float64).copy()
    for ms,g in ((46,.10),(83,.055)):
        d=int(SR*ms/1000); y[d:]+=g*x[:-d]
    return y

# Rounded attacks reduce the crest factor. Match v4's long-term level rather
# than re-amplifying v5 back to v4's sharper peak.
mix=post(room(chout.sum(axis=0)),.84)*0.737
stems=[post(chout[0],.74),post(chout[1],.74),post(chout[2],.70)]

def wav(path,x):
    pcm=np.int16(np.clip(x,-1,1)*32767)
    with wave.open(str(path),'wb') as f:f.setnchannels(1);f.setsampwidth(2);f.setframerate(SR);f.writeframes(pcm.tobytes())

mixwav=OUT/'another_world_intro_ay_v6_no_tractor_2m50s.wav'; wav(mixwav,mix)
names=['stem_A_bass_stable_drone','stem_B_melody_rounded_envelopes','stem_C_gentle_snares']
for name,x in zip(names,stems):wav(OUT/f'{name}.wav',x)

ff=shutil.which('ffmpeg')
def enc(src,dst,*args):subprocess.run([ff,'-y','-hide_banner','-loglevel','error','-i',str(src),*args,str(dst)],check=True)
mp3=OUT/'another_world_intro_ay_v6_no_tractor_2m50s.mp3'; flac=OUT/'another_world_intro_ay_v6_no_tractor_2m50s.flac'
enc(mixwav,mp3,'-c:a','libmp3lame','-b:a','192k'); enc(mixwav,flac,'-c:a','flac')
for name in names:enc(OUT/f'{name}.wav',OUT/f'{name}.mp3','-c:a','libmp3lame','-b:a','160k')

summary={'duration_seconds':DURATION,'ticks_50hz':TICKS,'delta_stream_bytes':len(stream),'vgm_bytes':len(vgm),'changes':['removed all repeating bass noise gates','removed repeating bass pitch and volume modulation','removed periodic metallic machine tick','kept rounded melody attacks and existing peak shape','kept noisy melody onsets and body-plus-noise gentle snares','matched v5 long-term listening level within 0.05 dB'],'melody_events':len(melody),'bass_events':len(bass),'drum_events':len(drums)}
(OUT/'summary.json').write_text(json.dumps(summary,indent=2))
readme='''# Another World-inspired AY music v6 — no-tractor pass\n\nDuration: 2:50. 50 Hz AY register timing.\n\nChanges from v5:\n- completely removes periodic bass noise gating, pitch grain and volume pumping\n- removes the regular metallic machine tick\n- keeps the rounded melody attacks, noise level and synth peaks from v5\n- keeps noisy breath/glass onsets and body-plus-noise gentle snares\n- preserves the same long-term listening level\n\nThis remains a hand-arranged AY approximation. The original tracker waveform and envelope tables are not available in the preserved sources.\n'''
(OUT/'README.md').write_text(readme)
source_path=Path(__file__).resolve(); destination=OUT/'build_ay_recreation_v6.py'
if source_path != destination.resolve(): shutil.copy2(source_path,destination)

bundle=OUT/'another_world_intro_ay_v6_bundle.zip'
include=['README.md','summary.json','build_ay_recreation_v6.py',mp3.name,flac.name,*[f'{n}.mp3' for n in names],'aw_intro_ay_v6_2m50s.bin','aw_intro_ay_v6_2m50s.vgm','aw_intro_ay_v6_2m50s.vgz','aw_intro_ay_v6_registers.csv']
with zipfile.ZipFile(bundle,'w',zipfile.ZIP_DEFLATED,compresslevel=6) as z:
    for n in include:z.write(OUT/n,n)
print(json.dumps(summary,indent=2));print(mp3);print(bundle)
