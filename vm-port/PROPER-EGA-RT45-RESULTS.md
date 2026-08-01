# Proper EGA + row-fill + cost-selected 4.5 fps

This build combines the real visual asset pack with the live EGA restore,
deep-child culling, unrolled cell fill, row-oriented full fill, coordinate
tables, cost-selected draw-event stream, and 268/298 presentation schedule.

Measured with the JSSpeccy core over the complete 2,980-tick workload:

| Build | Presentations | Refreshes | Seconds |
|---|---:|---:|---:|
| Proper EGA + row-fill | 298 | 11,815 | 236.30 |
| Proper EGA + row-fill + cost 4.5 fps | 268 | 10,164 | 203.28 |

The candidate completes 56,075 VM instructions with trace hash 40691. All 268
presentations are non-black and cover retained sample slots 1 through 298.

The historical cost-selected event mask is not pixel-equivalent after the real
bitmap/attribute/checkpoint streams are substituted: 64 retained presentations
match the 298-frame proper-EGA baseline exactly, with an average mismatch of
1,264/6,912 bytes. The artifact is therefore a measured experimental build,
not a claim of pixel-perfect or real-time output.
