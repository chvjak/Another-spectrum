# Another World on ZX Spectrum 128K

Consolidated experiments for porting the DOS-shareware intro and representative
gameplay to a stock ZX Spectrum 128K.

## Implementations

- `diff-stream/`: a pre-rendered 25 fps bank-5/bank-7 delta player. The final
  hybrid rebuild uses 6x6 text derived from the original RawGL font and presents
  all 4,113 frames in exactly 8,226 PAL refreshes (164.52 seconds).
- `vm-port/`: an intro-specific Z80 VM and live polygon renderer retaining the
  original 9,842-byte bytecode and 65,156-byte shape resource.
- `music/`: versioned 50 Hz AY register streams. Version 7 combines the v6
  no-tractor arrangement with keypad, brake, footsteps, and lightning effects.
- `sprite-eval/`: a 25 fps saved-under sprite/gameplay feasibility build with
  Lester, Buddy, twelve packed room backgrounds, and an interactive
  O/P/SPACE controls variant.

## Final status

The project proved the architecture and several important performance paths,
but it did not produce one live-VM snapshot that is simultaneously verified as
non-black, pixel-correct, and real-time:

- VM control flow is exact: 2,980 ticks, 56,075 bytecode instructions, and trace
  hash 40,691.
- The fixed real-asset renderer is exact for all 268 retained presentations,
  but takes 577.82 emulated seconds.
- The 4.5 fps benchmark reaches 7,866 refreshes, inside the 8,226-refresh
  deadline, but its `cost-4p5-ay.sna` payload is black when loaded through the
  real JSSpeccy snapshot path. It is a performance result, not a working demo.
- The latest dense-restore and attribute-generation changes assemble and pass a
  runtime smoke test against the existing site snapshot, but the production
  visual build was not regenerated from the missing historical inputs.
- The gameplay-room and controls experiments meet their 25 fps deadline with
  no recorded misses on the tested JSSpeccy core.

The diff-stream hybrid remains the only fully cadence-verified path at the
correct 164.52-second duration; it trades live vector rendering for pre-rendered
external-media blocks.

See [`docs/PROJECT-WRAP-UP.md`](docs/PROJECT-WRAP-UP.md) for the measured
findings, caveats, retained artifacts, and branch-consolidation record.

## Repository policy

Builds, benchmarks, emulator tests, and artifact generation are local. No
GitHub Actions workflows are retained. Original game data, Spectrum ROMs,
emulator binaries, and most generated media are intentionally excluded; each
implementation README lists its external inputs.
