#!/usr/bin/env python3
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path
from PIL import Image
import os
import struct

ROOT = Path(__file__).parent
OUT = ROOT / os.environ.get("SPECCY_OUTPUT", "full-speccy")
CAPTURE = ROOT / os.environ.get("SPECCY_CAPTURE", "captured")
WAIT_FRAMES = int(os.environ.get("SPECCY_WAIT_FRAMES", "10"))
OUT.mkdir(exist_ok=True)
PAL = [
    (0, 0, 0), (32, 48, 192), (192, 64, 16), (192, 64, 192),
    (64, 176, 16), (80, 192, 176), (224, 192, 16), (192, 192, 192),
    (0, 0, 0), (48, 64, 255), (255, 64, 48), (255, 112, 240),
    (80, 224, 16), (80, 224, 255), (255, 232, 80), (255, 255, 255),
]

def spectrum_offset(y, xb):
    return ((y & 0xc0) << 5) | ((y & 7) << 8) | ((y & 0x38) << 2) | xb

def convert(item):
    number, path = item
    im = Image.open(path).convert("RGB").resize((256, 192), Image.Resampling.LANCZOS)
    px = im.load()
    out = bytearray(6912)
    for cy in range(24):
        for cx in range(32):
            colors = [px[cx * 8 + x, cy * 8 + y] for y in range(8) for x in range(8)]
            best = None
            for bright in (0, 1):
                base = bright * 8
                for paper in range(8):
                    for ink in range(8):
                        p, q = PAL[base + paper], PAL[base + ink]
                        err = sum(min(
                            (r-p[0])**2 + (g-p[1])**2 + (b-p[2])**2,
                            (r-q[0])**2 + (g-q[1])**2 + (b-q[2])**2
                        ) for r, g, b in colors)
                        if best is None or err < best[0]:
                            best = (err, bright, paper, ink, p, q)
            _, bright, paper, ink, p, q = best
            out[6144 + cy * 32 + cx] = (bright << 6) | (paper << 3) | ink
            for yy in range(8):
                bits = 0
                for xx in range(8):
                    r, g, b = colors[yy * 8 + xx]
                    dp = (r-p[0])**2 + (g-p[1])**2 + (b-p[2])**2
                    dq = (r-q[0])**2 + (g-q[1])**2 + (b-q[2])**2
                    bits = (bits << 1) | (dq < dp)
                out[spectrum_offset(cy * 8 + yy, cx)] = bits
    dest = OUT / f"frame-{number:04}.scr"
    dest.write_bytes(out)
    return number

def spans(old, new):
    changed = [i for i, (a, b) in enumerate(zip(old, new)) if a != b]
    result, i = [], 0
    while i < len(changed):
        start = end = changed[i]
        i += 1
        while i < len(changed) and changed[i] - end <= 3 and changed[i] - start < 255:
            end = changed[i]
            i += 1
        result.append((start, new[start:end + 1]))
    return result

class Asm:
    def __init__(self, origin):
        self.origin, self.code, self.labels, self.fixups = origin, bytearray(), {}, []
    @property
    def pc(self): return self.origin + len(self.code)
    def emit(self, *values): self.code.extend(values)
    def label(self, name): self.labels[name] = self.pc
    def jr(self, opcode, label):
        self.emit(opcode, 0); self.fixups.append((len(self.code)-1, label, "rel"))
    def absolute(self, opcode, label):
        self.emit(opcode, 0, 0); self.fixups.append((len(self.code)-2, label, "abs"))
    def finish(self):
        for pos, label, kind in self.fixups:
            addr = self.labels[label]
            if kind == "rel":
                self.code[pos] = (addr - (self.origin + pos + 1)) & 255
            else:
                self.code[pos:pos+2] = struct.pack("<H", addr)
        return bytes(self.code)

def player_code(frame_count):
    a = Asm(0x5b00)
    a.emit(0xf3, 0x31, 0xf0, 0x7f, 0xdd, 0x21, 0x00, 0x80, 0xfd, 0x21, 0x00, 0x40, 0xaf)
    a.absolute(0x32, "target")
    a.emit(0x3e, frame_count)
    a.absolute(0x32, "remaining")
    a.emit(0x3e, 0x5c, 0xed, 0x47, 0xed, 0x5e)
    a.label("frame"); a.emit(0xf3)
    a.label("span")
    a.emit(0xdd,0x5e,0,0xdd,0x23,0xdd,0x56,0,0xdd,0x23,0x7a,0xfe,0xff)
    a.jr(0x28, "present")
    a.emit(0xdd,0x4e,0,0xdd,0x23,0x06,0,0xfd,0xe5,0xe1,0x19,0xeb,
           0xdd,0xe5,0xe1,0xed,0xb0,0xe5,0xdd,0xe1)
    a.jr(0x18, "span")
    a.label("present")
    a.absolute(0x3a, "target"); a.emit(0xb7); a.jr(0x20, "show7")
    a.emit(0x3e,0x07,0xfd,0x21,0,0xc0); a.jr(0x18, "flip")
    a.label("show7"); a.emit(0x3e,0x0f,0xfd,0x21,0,0x40)
    a.label("flip"); a.emit(0x01,0xfd,0x7f,0xed,0x79)
    a.absolute(0x3a, "target"); a.emit(0xee,1); a.absolute(0x32, "target")
    a.emit(0xfb,0x06,WAIT_FRAMES)
    a.label("wait"); a.emit(0x76,0x10,0xfd)
    a.absolute(0x3a, "remaining"); a.emit(0x3d); a.absolute(0x32, "remaining")
    a.jr(0x20, "frame")
    a.label("hold"); a.emit(0x76); a.jr(0x18, "hold")
    a.label("target"); a.emit(0)
    a.label("remaining"); a.emit(0)
    return a.finish()

def encode(frames):
    states = [bytes(6912), bytes(6912)]
    encoded = bytearray()
    for i, frame in enumerate(frames):
        target = i & 1
        for offset, data in spans(states[target], frame):
            encoded += struct.pack("<HB", offset, len(data)) + data
        encoded += b"\xff\xff"
        states[target] = frame
    return encoded

def snapshot(frames, stream, reel_no):
    code = player_code(len(frames))
    pages = [bytearray(0x4000) for _ in range(8)]
    pages[2][:len(stream)] = stream
    pages[5][0x1b00:0x1b00+len(code)] = code
    pages[5][0x1cff] = 0x10
    pages[5][0x1d00] = 0x5d
    pages[5][0x1d10:0x1d13] = bytes((0xfb,0xed,0x4d))
    header = bytearray(27)
    header[19], header[23:25], header[25] = 4, struct.pack("<H",0x7ff0), 2
    blob = bytearray(header) + pages[5] + pages[2] + pages[0]
    blob += struct.pack("<HBB", 0x5b00, 0, 0)
    for n in (1,3,4,6,7): blob += pages[n]
    path = OUT / f"reel-{reel_no:02}.sna"
    path.write_bytes(blob)
    return path

source = sorted(CAPTURE.glob("frame-*.ppm"))
work = [(int(p.stem.split("-")[1]), p) for p in source]
missing = [(n,p) for n,p in work if not (OUT / f"frame-{n:04}.scr").exists()]
if missing:
    with ProcessPoolExecutor(max_workers=min(8, os.cpu_count() or 1)) as pool:
        for done, number in enumerate(pool.map(convert, missing), 1):
            if done % 20 == 0: print(f"converted {done}/{len(missing)}", flush=True)

all_frames = [(n, (OUT / f"frame-{n:04}.scr").read_bytes()) for n,_ in work]
reels, start = [], 0
while start < len(all_frames):
    best = None
    for end in range(start + 1, min(start + 255, len(all_frames)) + 1):
        stream = encode([data for _,data in all_frames[start:end]])
        if len(stream) > 0x3f00: break
        best = (end, stream)
    if best is None: raise RuntimeError(f"single frame at {start} exceeds reel")
    end, stream = best
    path = snapshot(all_frames[start:end], stream, len(reels))
    reels.append((path, start, end, len(stream)))
    start = end

manifest = ["reel,start_frame,end_frame,frames,stream_bytes"]
for path,start,end,size in reels:
    manifest.append(f"{path.name},{start},{end-1},{end-start},{size}")
(OUT / "reels.csv").write_text("\n".join(manifest) + "\n")
print(f"built {len(all_frames)} frames in {len(reels)} reels")
for row in reels: print(row[0].name, row[2]-row[1], row[3])
