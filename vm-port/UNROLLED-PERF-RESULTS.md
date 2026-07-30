# Specialized unrolled copy/fill benchmark

Full 2,980-tick benchmark on the measured EGA-copy winner. All accepted variants completed 56,075 VM instructions, 6,931 primitives and 298 presentations with identical visible and both-screen hashes and zero VM/renderer errors.

| Variant | Refreshes | Seconds | Saved |
|---|---:|---:|---:|
| baseline | 10,180 | 203.60 | — |
| width-1 loop control | 10,180 | 203.60 | 0.000% |
| width-1 unrolled | 10,176 | 203.52 | 0.039% |
| width 2 | 10,177 | 203.54 | 0.029% |
| width 3 | 10,177 | 203.54 | 0.029% |
| width 4 | 10,177 | 203.54 | 0.029% |
| width 8 | 10,177 | 203.54 | 0.029% |
| width 16 | 10,177 | 203.54 | 0.029% |
| width 32, two 16-LDI chunks | 10,177 | 203.54 | 0.029% |
| unrolled 8-line cell fill | 9,925 | 198.50 | 2.505% |
| **width-1 restore + cell fill** | **9,922** | **198.44** | **2.534%** |

Winner: `u-w1-fill`. Snapshot container remains 131,103 bytes. Winning VM is 4,807 bytes; renderer is 3,670 bytes with 138 bytes remaining before the event-run region.
