# Row-oriented full-fill benchmark

| Variant | Refreshes | Seconds | Saved vs baseline |
|---|---:|---:|---:|
| r-baseline | 9922 | 198.44 | 0.000% |
| r-row-ldir | 9416 | 188.32 | 5.100% |
| r-row-ldi32 | 9413 | 188.26 | 5.130% |
| r-row-vertical-indexed | 9155 | 183.10 | 7.730% |
| r-row-vertical-exx | 9155 | 183.10 | 7.730% |
| r-row-vertical-exx-table | 9154 | 183.08 | 7.740% |

Winner: **r-row-vertical-exx-table**.

All accepted variants match visible output, VM trace, primitive count, and error-free completion.
