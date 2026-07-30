# JSSpeccy SNA verification

Tested `cost-4p5-ay.sna` through JSSpeccy 3.2.0 `parseSNAFile` and worker `loadSnapshot` semantics, using the same pinned `jsspeccy-core.wasm` as the performance benchmark.

## Result

The snapshot is accepted and the program executes to completion, but the complete displayed output is black.

- 8,226 host refreshes
- VM tick 2,980
- 56,075 VM instructions
- trace hash 40,691
- 268 presentations
- zero VM opcode errors
- first presentation at refresh 78
- maximum non-black pixels in any sampled JSSpeccy framebuffer: **0**

The original SNA header is `PC=0x8000`, `SP=0xBFF0`, IFF1/IFF2 enabled, IM2, paging flags 0. Two header variants were also tested:

1. IFF disabled, IM2 retained.
2. IFF disabled and IM1 selected to match the benchmark harness.

Both variants produced exactly the same all-black output and completed successfully. The black screen is therefore not caused by JSSpeccy's SNA header restoration or an early interrupt.

## Why the benchmark did not expose this

`ay_rt45_runner.mjs` did not load the snapshot through JSSpeccy's SNA loader. It copied the RAM pages directly and forced PC, SP, interrupt state and paging. It validated VM counters and screen hashes against a baseline whose displayed screen data was also black.

The published MP4 was not captured from the SNA framebuffer. The recording workflow captured frames from the original `another_js` shareware engine and passed those frames through the Spectrum-style quantizer, then muxed the synthesized AY track.

## Conclusion

`cost-4p5-ay.sna` is computationally valid but not a working visual demo. Its visual asset / renderer payload produces black screen banks throughout the run. A new SNA must be rebuilt from a known non-black EGA / row-fill asset snapshot and then re-benchmarked through the actual JSSpeccy loader path.
