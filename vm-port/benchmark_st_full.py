#!/usr/bin/env python3
"""Build and compare baseline vs ST-style VM renderer in the emulator.

Requires the same locally supplied AW inputs, reference frames, ROMs and
JSSpeccy core as build_full_vm_port.py/run_full_vm_test.mjs.
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
BUILD = ROOT / "build-full"


def run(command: list[str]) -> None:
    subprocess.run(command, cwd=ROOT, check=True)


def snapshot_result(label: str) -> tuple[dict, dict]:
    manifest = json.loads((BUILD / "manifest.json").read_text())
    result = json.loads((BUILD / "test-results.json").read_text())
    shutil.copy2(BUILD / "manifest.json", BUILD / f"manifest-{label}.json")
    shutil.copy2(BUILD / "test-results.json", BUILD / f"test-results-{label}.json")
    shutil.copy2(
        BUILD / "another-world-vm-full.sna",
        BUILD / f"another-world-vm-full-{label}.sna",
    )
    return manifest, result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--zxasm", type=Path)
    args = parser.parse_args()
    build_args = [] if args.zxasm is None else ["--zxasm", str(args.zxasm)]

    run([sys.executable, "build_full_vm_port.py", *build_args])
    run(["node", "run_full_vm_test.mjs"])
    baseline_manifest, baseline = snapshot_result("baseline")

    run([sys.executable, "build_st_optimized.py", *build_args])
    run(["node", "run_full_vm_test.mjs"])
    st_manifest, st = snapshot_result("st")

    baseline_frames = baseline["host_frames"]
    st_frames = st["host_frames"]
    report = {
        "passed": bool(baseline["passed"] and st["passed"]),
        "trace_equal": (
            baseline["trace_hash"] == st["trace_hash"]
            and baseline["instruction_count"] == st["instruction_count"]
            and baseline["vm_tick"] == st["vm_tick"]
        ),
        "sampled_frames_equal": baseline["sampled_frames"] == st["sampled_frames"],
        "decoded_primitives_equal": (
            baseline["decoded_primitives"] == st["decoded_primitives"]
        ),
        "baseline_host_frames": baseline_frames,
        "st_host_frames": st_frames,
        "whole_run_speedup": baseline_frames / st_frames,
        "whole_run_saved_percent": (1 - st_frames / baseline_frames) * 100,
        "baseline_renderer_bytes": baseline_manifest["sizes"]["renderer"],
        "st_renderer_bytes": st_manifest["sizes"]["renderer"],
        "renderer_growth_bytes": (
            st_manifest["sizes"]["renderer"]
            - baseline_manifest["sizes"]["renderer"]
        ),
        "baseline_average_bitmap_mismatch": baseline["average_bitmap_mismatch"],
        "st_average_bitmap_mismatch": st["average_bitmap_mismatch"],
        "baseline_max_bitmap_mismatch": baseline["max_bitmap_mismatch"],
        "st_max_bitmap_mismatch": st["max_bitmap_mismatch"],
    }
    (BUILD / "st-ab-result.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2))
    return 0 if report["passed"] and report["trace_equal"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
