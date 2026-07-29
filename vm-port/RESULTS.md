# Full intro VM + runtime renderer results

## Correctness

The emulator reaches the request for part 16002 without an unsupported opcode
or renderer error:

- VM ticks: **2,980**
- original instructions: **56,075**
- rawgl trace hash: **0x9EF3**
- Z80 trace hash: **0x9EF3**
- sampled visual frames: **298**
- decoded runtime primitives: **7,938**

The trace hash covers every original `(PC, opcode)` pair in order. The five
checkpoint backgrounds are also compared byte-for-byte after Z80
decompression; all have zero mismatches.

## Resident representation

| Component | Bytes |
|---|---:|
| Z80 VM | 2,074 |
| Runtime renderer | 3,585 |
| Original bytecode | 9,842 |
| Original shapes | 65,156 |
| Compact text | 1,846 |
| Palette + decision tables | 1,040 |
| Dynamic liveness mask | 373 |
| Attribute change mask | 38 |
| LZSS attribute maps | 5,422 |
| Bitmap resource streams | 3,982 |
| Five page-0 checkpoints | 6,276 |

The original 74,998 bytes of bytecode and geometry remain authoritative.
Spectrum-specific visual additions total about 17 KB; most of that is palette
attributes and five static backgrounds, not per-frame geometry.

Estimated complete resident use, including screens and working memory, is
about **126.3 KB**, leaving roughly **4.8 KB aggregate free**. That free space
is fragmented, so the largest immediately usable block is smaller.

## Dirty restore

Each physical screen owns a 768-bit dirty map:

1. restore only cells touched the last time that bank was used;
2. draw the current foreground from original shape resources;
3. present the bank;
4. repeat independently for the other bank.

The metadata cost is **192 bytes total**. There is no list of dirty zones per
frame and no whole-screen comparison at runtime.

## Attribute stability

The indexed original page is used offline to assign stable logical PAPER/INK
roles to each Spectrum cell. Palette changes update only the corresponding
Spectrum colours; they never silently swap the meaning of existing bitmap
bits.

Bitmap checkpoints and the resumable attribute stream share one 2 KB LZSS
history buffer. After each checkpoint, the renderer restarts the compact
attribute stream and fast-forwards only its distinct maps. This avoids a
second 2 KB history buffer.

## Post-quantization draw elimination

An offline owner replay now classifies all 9,648 top-level shape and text
commands at the sampled Spectrum presentations:

- 1,984 clipped or zero-area calls;
- 2,069 point/sub-pixel calls;
- 4,703 calls overwritten before a sampled presentation;
- 125 static calls covered by the five existing checkpoints;
- 1,117 conservative surviving draw events.

The keep plan occupies 830 bytes as alternating run lengths. The VM consumes
one entry per original draw command, so bytecode and shape offsets are
unchanged. A rejected same-colour/cell pass is retained only as an analysis:
byte-level ablation showed that it increased error while saving fewer expanded
primitives.

Against an all-draw VM build, 253/298 sampled screens are byte-identical. The
remaining 45 differ by 155 bytes total (0.52 byte/frame, maximum 16 bytes in
one frame).

## Timing

The optimized full run takes **29,392 emulated refresh intervals**, down from
30,928. Decoded primitives fall from 7,938 to 7,007. The remaining workload is
therefore concentrated in large compound survivors rather than dead command
dispatch. The downloadable 59.8-second video
uses the VM's 298 sampled presentations at their intended 5 fps timing.

This is a size/correctness milestone, not a real-time claim. Profiling points
to a small set of repeated dense compounds; those should be the only geometry
precompiled into spans in the next pass.
