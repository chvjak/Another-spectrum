#!/usr/bin/env python3
"""Generate explicit VM source variants used by local performance experiments.

The output remains ordinary sjasmplus source.  Keeping the transformation in
the repository makes every benchmark SNA reproducible without maintaining a
second hand-edited copy of the VM.
"""

from __future__ import annotations

import argparse
from pathlib import Path


def replace_routine(source: str, label: str, next_label: str, body: str) -> str:
    start_marker = f"{label}:\n"
    end_marker = f"{next_label}:\n"
    start = source.find(start_marker)
    end = source.find(end_marker, start + len(start_marker))
    if start < 0 or end < 0:
        raise RuntimeError(f"could not locate {label}..{next_label}")
    return source[:start] + start_marker + body.rstrip() + "\n\n" + source[end:]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--live-backgrounds",
        action="store_true",
        help="render every page-0 construction instead of loading checkpoints",
    )
    parser.add_argument(
        "--profile-phase",
        action="store_true",
        help="mark the run_tasks interval at 0x9374 for exact emulator timing",
    )
    args = parser.parse_args()

    source = args.input.read_text(encoding="utf-8")
    if args.live_backgrounds:
        source = replace_routine(
            source,
            "checkpoint_for_tick",
            "unsupported",
            """        ; Measurement/reference variant: retain the original live
        ; resource construction at every tick.
        scf
        ret""",
        )
    if args.profile_phase:
        source = source.replace(
            "LAST_SAMPLE_BANK       EQU 0x9332\n",
            "LAST_SAMPLE_BANK       EQU 0x9332\nPROFILE_PHASE           EQU 0x9374\n",
            1,
        )
        marker = """main_loop:
        call wait_tick_slot
        call setup_tasks
        call run_tasks

        ld hl,(TICK)
"""
        replacement = """main_loop:
        call wait_tick_slot
        call setup_tasks
        ld a,1
        ld (PROFILE_PHASE),a
        call run_tasks
        xor a
        ld (PROFILE_PHASE),a

        ld hl,(TICK)
"""
        if source.count(marker) != 1:
            raise RuntimeError("could not locate main_loop run_tasks call")
        source = source.replace(marker, replacement, 1)

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(source, encoding="utf-8")


if __name__ == "__main__":
    main()
