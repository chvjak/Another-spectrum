#!/usr/bin/env python3
"""Build the rounded-machine AY v5 from the preserved v4 generator.

The musical arrangement, noise level and three-channel roles remain those of v4.
This pass only reduces the periodic 'tractor' quality of channel A and rounds the
sharp attack peaks of channel B. The generated mix is still normalized to the
same 0.84 peak as v4.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

HERE = Path(__file__).resolve().parent
V4 = HERE.parent / "v4" / "build_ay_recreation_v4.py"
EXPANDED = HERE / ".expanded_v5.py"

text = V4.read_text(encoding="utf-8")

replacements = {
    "OUT = Path(__file__).resolve().parent / 'generated'":
        "OUT = Path(__file__).resolve().parent / 'generated'",

    # Rounded melody envelope: preserve its sustain and level, remove the
    # one-refresh amplitude spike.
    "macro=[1.00,0.78,0.62,0.55,0.58,0.52,0.49,0.47]":
        "macro=[0.52,0.68,0.82,0.92,0.88,0.78,0.68,0.60,0.55,0.51]",
    "macro=[0.72,1.00,0.82,0.68,0.60,0.56,0.53,0.50]":
        "macro=[0.42,0.58,0.74,0.88,0.94,0.86,0.75,0.66,0.59,0.54]",

    # About one third less machine modulation, especially in the finale.
    "machine_windows=[(3,18,.55),(33,47,.40),(61,78,.48),(91,109,.52),(122,139,.56),(146,164,.68)]":
        "machine_windows=[(3,18,.36),(33,47,.27),(61,78,.32),(91,109,.35),(122,139,.37),(146,164,.44)]",
    "elif ms>0.2 and age%17==0: semitone=12":
        "elif ms>0.32 and age%37==0: semitone=7",
    "cents=2.2*math.sin(2*math.pi*age/53.0)+ms*(9*math.sin(2*math.pi*t/5)+3*math.sin(2*math.pi*t/11))":
        "cents=1.8*math.sin(2*math.pi*age/59.0)+ms*(5.2*math.sin(2*math.pi*t/7)+1.8*math.sin(2*math.pi*t/17))",
    "if ms>0.10 and (age%9)<6:":
        "if ms>0.12 and (age%13)<5:",
    "r[6]=max(4,min(25,round(18-ms*15 + 3*math.sin(2*math.pi*t/19))))":
        "r[6]=max(8,min(27,round(21-ms*10 + 2*math.sin(2*math.pi*t/23))))",

    # Keep noisy attacks, but replace octave/fifth jabs with a tiny three-tick
    # colouration into the target pitch.
    "if age==0: semi=12\n        elif age==1 and e.instrument=='glass': semi=7\n        elif age==2 and e.instrument=='glass': semi=12":
        "if age==0: semi=3 if e.instrument=='glass' else 2\n        elif age==1: semi=2 if e.instrument=='glass' else 1\n        elif age==2 and e.instrument=='glass': semi=1",

    # Slightly softer extreme edge, then normalize to exactly the same peak.
    "x=np.tanh(x*1.25)": "x=np.tanh(x*1.12)",
    "sos=butter(2,[35,9500],btype='bandpass',fs=SR,output='sos')":
        "sos=butter(2,[35,8400],btype='bandpass',fs=SR,output='sos')",

    "aw_intro_ay_v4_2m50s.bin": "aw_intro_ay_v5_2m50s.bin",
    "aw_intro_ay_v4_registers.csv": "aw_intro_ay_v5_registers.csv",
    "aw_intro_ay_v4_2m50s.vgm": "aw_intro_ay_v5_2m50s.vgm",
    "aw_intro_ay_v4_2m50s.vgz": "aw_intro_ay_v5_2m50s.vgz",
    "another_world_intro_ay_v4_noisier_envelopes_2m50s.wav":
        "another_world_intro_ay_v5_rounded_machine_2m50s.wav",
    "another_world_intro_ay_v4_noisier_envelopes_2m50s.mp3":
        "another_world_intro_ay_v5_rounded_machine_2m50s.mp3",
    "another_world_intro_ay_v4_noisier_envelopes_2m50s.flac":
        "another_world_intro_ay_v5_rounded_machine_2m50s.flac",
    "stem_A_bass_machine_noise": "stem_A_bass_softer_machine_noise",
    "stem_B_melody_sampled_envelopes": "stem_B_melody_rounded_envelopes",
    "another_world_intro_ay_v4_bundle.zip": "another_world_intro_ay_v5_bundle.zip",
    "build_ay_recreation_v4.py": "build_ay_recreation_v5.py",
    "Another World-inspired AY music v4 — noisier / sampled-envelope pass":
        "Another World-inspired AY music v5 — rounded machine/noise pass",
    "Changes from v3:": "Changes from v4:",
}

for old, new in replacements.items():
    if old not in text:
        raise RuntimeError(f"v4 source fragment not found: {old!r}")
    text = text.replace(old, new)

old_summary = (
    "summary={'duration_seconds':DURATION,'ticks_50hz':TICKS,"
    "'delta_stream_bytes':len(stream),'vgm_bytes':len(vgm),"
    "'changes':['more continuous machine-noise gating on A',"
    "'noise transients on melody attacks','sample-like pitch macros on note attacks',"
    "'two-stage sampled-style melody volume envelopes','body+noise gentle snares',"
    "'sparse metallic machine ticks'],'melody_events':len(melody),"
    "'bass_events':len(bass),'drum_events':len(drums)}"
)
new_summary = (
    "summary={'duration_seconds':DURATION,'ticks_50hz':TICKS,"
    "'delta_stream_bytes':len(stream),'vgm_bytes':len(vgm),"
    "'changes':['reduced periodic bass noise gating while preserving ambience',"
    "'slower less regular machine pitch modulation','rounded multi-tick melody attacks',"
    "'removed octave-spike melody transients',"
    "'slightly softer output bandwidth at unchanged peak level',"
    "'body+noise gentle snares retained'],'melody_events':len(melody),"
    "'bass_events':len(bass),'drum_events':len(drums)}"
)
if old_summary not in text:
    raise RuntimeError("v4 summary block not found")
text = text.replace(old_summary, new_summary)

old_readme = (
    "Changes from v4:\\n"
    "- bass is roughened with low-level AY noise gating and short octave/fifth attack macros\\n"
    "- melody attacks include brief noise and harmonic pitch macros\\n"
    "- melody volume macros use fast sample-like decay into a quieter sustain, rather than generic ADSR\\n"
    "- snares combine a short descending tone body with a longer noise tail\\n"
    "- sparse metallic ticks and changing noise periods make the machine ambience less static"
)
new_readme = (
    "Changes from v4:\\n"
    "- keeps the same overall normalized level and useful AY noise texture\\n"
    "- reduces regular bass noise gates and rapid pitch modulation that sounded like a tractor\\n"
    "- replaces one-tick melody octave/fifth spikes with a rounded 4–5 tick attack\\n"
    "- softens only the extreme high-frequency edge; melody sustain and noise remain present\\n"
    "- retains body-plus-noise gentle snares and sparse metallic details"
)
if old_readme not in text:
    raise RuntimeError("v4 README block not found")
text = text.replace(old_readme, new_readme)

# The expanded script runs beside this file, so its relative generated directory
# is music/v5/generated. It is retained there as the exact expanded source used.
EXPANDED.write_text(text, encoding="utf-8")
try:
    subprocess.run(["python3", str(EXPANDED)], check=True)
finally:
    EXPANDED.unlink(missing_ok=True)
