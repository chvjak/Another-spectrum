#!/usr/bin/env python3
"""Reproduce the real-resource VM SNA and its local JSSpeccy verification."""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parent


def run(command: list[str], **kwargs: object) -> None:
    print("+", " ".join(command), flush=True)
    subprocess.run(command, check=True, **kwargs)


def capture(command: list[str], output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    print("+", " ".join(command), ">", output, flush=True)
    with output.open("wb") as stream:
        subprocess.run(command, check=True, stdout=stream)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--another-js", type=Path, required=True)
    parser.add_argument("--sjasmplus", type=Path, required=True)
    parser.add_argument("--jsspeccy-core", type=Path)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()

    another_js = args.another_js.resolve()
    sjasmplus = args.sjasmplus.resolve()
    output = args.out.resolve()
    captures = output / "captures"
    trace = output / "optimizer-trace.log"
    text_data = output / "compact-text.bin"
    base = output / "bootstrap" / "baseline.sna"
    final_dir = output / "vm"
    output.mkdir(parents=True, exist_ok=True)

    data_js = another_js / "ootwdemo.js"
    engine_js = another_js / "another.min.js"
    for path in (data_js, engine_js, sjasmplus):
        if not path.exists():
            raise FileNotFoundError(path)

    capture(
        ["node", str(ROOT / "capture_original_colour_preview.mjs"), str(data_js), str(engine_js), "--indexed"],
        captures / "indexed.bin",
    )
    capture(
        ["node", str(ROOT / "capture_original_colour_preview.mjs"), str(data_js), str(engine_js), "--page3-snapshots"],
        captures / "page3.bin",
    )
    capture(
        ["node", str(ROOT / "capture_original_colour_preview.mjs"), str(data_js), str(engine_js), "--palette-ids"],
        captures / "palette-ids.bin",
    )
    run(["node", str(ROOT / "generate_optimizer_trace.mjs"), str(data_js), str(engine_js), str(trace)])
    run(["node", str(ROOT / "export_another_js_text.mjs"), str(data_js), str(trace), str(text_data)])
    run(
        [
            sys.executable,
            str(ROOT / "minimal_full_ab.py"),
            "--source-dir", str(ROOT),
            "--resource-js", str(data_js),
            "--text-data", str(text_data),
            "--sjasmplus", str(sjasmplus),
            "--out", str(base.parent),
            "--baseline-only",
        ]
    )
    run(
        [
            sys.executable,
            str(ROOT / "build_original_visuals.py"),
            "--indexed-capture", str(captures / "indexed.bin"),
            "--page3-capture", str(captures / "page3.bin"),
            "--palette-ids", str(captures / "palette-ids.bin"),
            "--trace", str(trace),
            "--base-sna", str(base),
            "--renderer", str(ROOT / "renderer_full.asm"),
            "--vm", str(ROOT / "vm_full.asm"),
            "--sjasmplus", str(sjasmplus),
            "--out", str(final_dir),
        ]
    )
    built = final_dir / "another-world-original-render-fixed.sna"
    named = final_dir / "another-world-vm-fast-backgrounds.sna"
    shutil.copy2(built, named)

    verification = None
    if args.jsspeccy_core is not None:
        profile = final_dir / "local-profile.json"
        captures_dir = final_dir / "local-captures"
        run(
            [
                "node",
                str(ROOT / "profile_snapshot.mjs"),
                str(args.jsspeccy_core.resolve()),
                str(named),
                str(profile),
                str(captures_dir),
            ]
        )
        verification = json.loads(profile.read_text(encoding="utf-8"))
        if not verification["completed"] or verification["retained_presentations"] != 298:
            raise RuntimeError("local emulator verification did not complete all 298 presentations")

    print(
        json.dumps(
            {
                "sna": str(named),
                "manifest": str(final_dir / "manifest.json"),
                "verified": verification is not None,
                "refreshes": verification["total_refreshes"] if verification else None,
                "screen_sequence_sha256": verification["screen_sequence_sha256"] if verification else None,
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
