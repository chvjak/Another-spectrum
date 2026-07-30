# 4.5 fps real-time benchmark

Measured with the complete 2,980-tick emulator workload on the row-oriented full-fill winner.

Baseline: **9,154 refreshes / 183.08 s / 298 presentations**.
Target: **8,226 refreshes / 164.52 s**.

| Plan | Rendered presentations | Refreshes | Runtime | Saved vs baseline | Target margin |
|---|---:|---:|---:|---:|---:|
| uniform-4p5 | 268 | 8,183 | 163.66 s | 10.61% | 43 refreshes / 0.86 s |
| cost-4p5 | 268 | 7,866 | 157.32 s | 14.07% | 360 refreshes / 7.20 s |
| balanced-4p5 | 268 | 7,866 | 157.32 s | 14.07% | 360 refreshes / 7.20 s |

**Winner: `cost-4p5`. Real time achieved.**

Validation for every plan:

- 2,980 VM ticks
- 56,075 bytecode instructions
- trace hash 40691
- all 298 original sample slots consumed
- exactly 268 presentations rendered
- retained slot sequence exactly matched the plan
- every retained screen was byte-identical to the corresponding frame of the 298-frame baseline
- zero VM or renderer errors

The winning plan removes 30 high-cost presentations, never two adjacent presentations in this measured schedule. Its final-pixel ownership pass keeps 1,020 of 9,648 draw events and produces a 752-byte event-run stream. The VM remains 4,807 bytes with 57 bytes left before its fixed variable region; the 128K SNA remains 131,103 bytes.
