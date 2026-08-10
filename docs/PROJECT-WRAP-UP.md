# Project wrap-up

Date: 2026-08-10

This document records the final technical conclusions and the branch cleanup
that produced the consolidated `main` history. Measurements below are preserved
as originally observed; incompatible benchmarks are not combined into a single
claim.

## Conclusions

### Correct-duration diff stream

The hybrid AWD2 path is the finished presentation solution:

- 4,113 presentations at 25 fps;
- exactly two 50 Hz Spectrum refreshes per presentation;
- exactly 8,226 refreshes / 164.52 seconds overall;
- 27 external-media blocks with the four-byte delta merge gap;
- original RawGL 8x8 glyphs area-resized to 6x6 at build time;
- alternating hidden bank decode and vblank presentation;
- AY v7 consumed at 50 register updates per second.

This is a build-time/pre-rendered representation, not a live polygon renderer.
See `diff-stream/HYBRID-AW-FONT.md` and `music/README.md`.

### Live VM and renderer

The Z80 VM retains the original control and geometry data:

| Property | Result |
|---|---:|
| VM ticks | 2,980 |
| Original instructions | 56,075 |
| Trace hash | 40,691 (`0x9EF3`) |
| Original bytecode | 9,842 bytes |
| Original shapes | 65,156 bytes |
| Sample slots | 298 |

The main renderer findings are deliberately separated:

| Build or experiment | Correctness | Runtime result | Interpretation |
|---|---|---:|---|
| Size-first VM baseline | Exact VM completion; approximate visuals | 29,392 refreshes | Correct architecture, far from real-time |
| Row-oriented fill winner | Output/trace matched its benchmark baseline | 9,154 refreshes | 7.74% faster than the measured row-fill baseline |
| Cost-selected 4.5 fps | 268 retained frames matched its baseline | 7,866 refreshes | CPU schedule meets the 8,226-refresh target |
| `cost-4p5-ay.sna` through real JSSpeccy loader | VM completes; displayed banks remain black | 8,226 host refreshes | Not a valid visual demo; prior harness copied RAM and validated a black baseline |
| Fixed proper-EGA build | 268/268 retained screens byte-exact against the generated Spectrum reference | 28,891 refreshes / 577.82 s | Visually correct live renderer, not real-time |
| Dense restore + attribute generations | Assembles; existing site SNA smoke test completes with zero renderer errors | 8,228 host refreshes for the tested site SNA | Optimization code is retained, but a fresh production visual artifact was not regenerated |

Consequently, there is no defensible claim that the repository contains a
single live-rendered snapshot that is both visually verified and real-time.
`vm-port/JSSPECCY-SNA-VERIFICATION.md`,
`vm-port/PROPER-EGA-RT45-RESULTS.md`, and
`vm-port/RT45-RESTORE-ATTRIBUTE-RESULTS.md` contain the primary evidence.

### Renderer optimization findings

- Full-cell unrolled fill saved 2.505%; width-specific restore/copy unrolling
  was nearly noise (at most 0.039%).
- Row-oriented vertical fill with an EXX/table path was the best exact tested
  fill at 7.74% over its baseline.
- The final-pixel ownership pass retained 1,020 of 9,648 draw events and encoded
  the plan in 752 bytes for the cost-selected schedule.
- Approximate 8.8 DDA measured 1.48x faster in the relative model, but only 395
  of 5,000 border-triangle framebuffers were exact. It is not a drop-in exact
  rasterizer.
- Offline DDA plus changed-byte replay modeled 2.64x over the current
  Bresenham/table path. This result excludes paging, contention, restoration,
  attributes, interrupts, and assembled/emulated instruction timing.
- Dense dirty restoration and per-screen attribute generations are safe runtime
  ideas; the exact production visual rebuild remains unverified because the
  historical indexed captures/build inputs are absent.

### Gameplay feasibility

The committed v4.2 reference contains twelve actual gameplay-room screens and
the monochrome actor/laser experiment:

- snapshot size: 131,103 bytes;
- snapshot SHA-256:
  `66cd9acfc084f883cc781f7659ac23f5b711bebac8f905f7bf86c7657f16dfe9`;
- twelve distinct rendered background hashes observed;
- 1,227 presentations in 2,600 refreshes;
- 99.02% of ordinary presentation intervals were exactly two refreshes;
- zero 40 ms deadline misses; maximum render span was one interrupt boundary.

The interactive controls variant uses O/P/SPACE for left/right/fire, keeps
Buddy at a trailing offset, and passed emulator-driven movement, follow,
fire/release, and timing checks with zero deadline misses. These are feasibility
prototypes, not an integrated port of the complete game.

## Retained artifacts and caveats

- `sprite-eval/artifacts/another-world-gameplay-rooms-v4.2-25fps.sna` is kept
  because it is small, independently hashed, and directly verifiable.
- Contact sheets and machine-readable manifests are kept next to the gameplay
  experiment.
- VM production snapshots, videos, original game resources, ROMs, JSSpeccy
  binaries, and most generated audio remain external.
- AY v7's committed SFX schedule is the audition-derived schedule described by
  `music/v7/README.md`; do not treat it as a proven VM-command-derived sync.
- A benchmark result is valid only for its documented baseline. In particular,
  the black-SNA real-time result and the slow proper-EGA visual result must not
  be combined.

## Branch consolidation

The final consolidation merge makes these distinct branch tips direct history
parents, then applies this documentation/cleanup commit:

| Branch tip | Commit | Retained reason |
|---|---|---|
| `codex/rt45-vm-optimization` | `04559a6` | Latest VM restore/attribute changes plus proper-EGA and polygon work |
| `agent/gameplay-backgrounds-v4-fix` | `24a3548` | Verified twelve-room v4.2 artifact and background hashes |
| `agent/gameplay-controls` | `2ae6266` | Interactive O/P/SPACE experiment and verifier |
| `jsspeccy-sna-verification` | `47c389a` | Actual snapshot-loader negative result and local verification harness |
| `hybrid-diffstream-aw-font` | `38ce08f` | Correct-cadence diff stream, 6x6 font, and AY v7 history |
| `render-rt45-demo` | `6c9bbc2` | Superseded render experiment retained as history only |

Every other remote branch tip is already an ancestor of one of those tips or
of the recovered `main` history:

- VM/benchmark chain: `st-span-optimizations`,
  `unrolled-copy-fill-tests`, `row-oriented-full-fill`, `rt-4p5fps`,
  `rt-4p5fps-ay`, `proper-ega`, `agent/polygon-sota-benchmark`,
  `agent/sprite-background-eval`, and `agent/vm-runtime-optimized`.
- Diff-stream chain: `probe-do-not-use`, `diff-stream-music-check`,
  `diff-stream-music`, and all eight
  `backup/diff-stream-music-before-sfx-v7*` refs (the eight backups point to the
  same commit).
- Recovery refs: `backup/accidental-empty-main-34c5cfb`,
  `backup/recovery-markers-before-restore`, and
  `recovery/original-main-3c16c71`.

After the consolidation reaches `main`, those remote refs carry no unique
history and can be deleted. `main` is the only intended long-lived branch.

## Local validation policy

No GitHub Actions workflow is part of the final tree. Use local tools and the
exact external inputs named by each implementation README. At minimum, a
maintenance check should validate Python/JavaScript/shell syntax, parse every
committed JSON file, verify committed artifact hashes, and confirm that every
retired branch tip is reachable from `main` before deleting refs.
