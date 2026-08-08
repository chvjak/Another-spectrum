#!/usr/bin/env python3
"""Combine real-intro emulator, renderer and semantic measurements as JSON."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
from collections import Counter, defaultdict
from pathlib import Path

import build_original_visuals as visuals
import lzss


STAGE_NAMES = {
    1: "Interplay logo / bitmap 18 load",
    49: "Interplay-to-Delphine transition",
    54: "Delphine Software logo / bitmap 71",
    102: "copyright/title transition",
    188: "Ferrari/parking setup",
    190: "Ferrari/parking",
    302: "Ferrari/parking detail",
    403: "door/corridor",
    776: "elevator transition",
    1053: "elevator/doorway",
    1087: "laboratory entrance",
    1171: "laboratory/desk",
    2159: "accelerator console text",
    2209: "accelerator/tunnel setup",
    2211: "accelerator/tunnel",
    2899: "late title transition",
    2939: "Out of This World title / bitmap 19",
}
CHECKPOINT_TICKS = {190, 302, 403, 1053, 2211}


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def sha256_paths(paths: list[Path]) -> str:
    digest = hashlib.sha256()
    for path in sorted(paths):
        digest.update(path.read_bytes())
    return digest.hexdigest()


def semantic_trace(path: Path) -> dict:
    tick = -1
    totals: Counter[str] = Counter()
    by_tick: dict[int, Counter[str]] = defaultdict(Counter)
    copies: Counter[str] = Counter()
    for raw in path.read_text(encoding="utf-8", errors="replace").splitlines():
        if raw.startswith("TRACE_TICK "):
            tick = int(raw.split()[1])
        elif raw.startswith("SEM quadstrip"):
            match = re.search(r"buffer=(\d+).*vertices=(\d+)", raw)
            assert match
            buffer, vertices = map(int, match.groups())
            totals["polygons"] += 1
            totals["vertices"] += vertices
            by_tick[tick][f"polygons_page{buffer}"] += 1
            by_tick[tick][f"vertices_page{buffer}"] += vertices
        elif raw.startswith("SEM point"):
            buffer = int(re.search(r"buffer=(\d+)", raw).group(1))  # type: ignore[union-attr]
            totals["points"] += 1
            by_tick[tick][f"points_page{buffer}"] += 1
        elif raw.startswith("SEM glyph"):
            buffer = int(re.search(r"buffer=(\d+)", raw).group(1))  # type: ignore[union-attr]
            totals["glyphs"] += 1
            by_tick[tick][f"glyphs_page{buffer}"] += 1
        elif raw.startswith("SEM clear"):
            buffer = int(re.search(r"buffer=(\d+)", raw).group(1))  # type: ignore[union-attr]
            totals["clears"] += 1
            by_tick[tick][f"clears_page{buffer}"] += 1
        elif raw.startswith("SEM present"):
            totals["presentations"] += 1
        elif raw.startswith("SEM copy"):
            match = re.search(r"dst=(\d+) src=(\d+)", raw)
            assert match
            dst, src = map(int, match.groups())
            copies[f"{src}->{dst}"] += 1
            totals["copies"] += 1
            by_tick[tick][f"copies_{src}_to_{dst}"] += 1
        elif raw.startswith("vid_opcd_event "):
            totals["draw_events"] += 1
        elif raw.startswith("Script::op_drawString"):
            totals["draw_events"] += 1
    return {
        "totals": dict(totals),
        "copy_operations": dict(sorted(copies.items())),
        "by_tick": by_tick,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--profile", type=Path, required=True)
    parser.add_argument("--instrumented", type=Path, required=True)
    parser.add_argument("--exact-profile", type=Path, required=True)
    parser.add_argument("--live-exact-profile", type=Path, required=True)
    parser.add_argument("--live-instrumented-profile", type=Path, required=True)
    parser.add_argument("--trace", type=Path, required=True)
    parser.add_argument("--indexed-capture", type=Path, required=True)
    parser.add_argument("--page3-capture", type=Path, required=True)
    parser.add_argument("--palette-ids", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--comparison", type=Path, required=True)
    parser.add_argument("--reference-screens", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()

    profile = read_json(args.profile)
    instrumented = read_json(args.instrumented)
    exact = read_json(args.exact_profile)
    live_exact = read_json(args.live_exact_profile)
    live_instrumented = read_json(args.live_instrumented_profile)
    manifest = read_json(args.manifest)
    comparison = read_json(args.comparison)
    semantic = semantic_trace(args.trace)

    visible, page0, palettes = visuals.load_capture(args.indexed_capture)
    page3, page3_palettes = visuals.load_page3_capture(args.page3_capture)
    palette_ids = visuals.load_palette_ids(args.palette_ids)
    visible = visuals.resize_indexes(visible)
    page0 = visuals.resize_indexes(page0)
    page3 = visuals.resize_indexes(page3)
    visual_data = visuals.build_visual_data(
        visible, page0, palettes, page3, page3_palettes, palette_ids
    )

    trace_ticks: dict[int, Counter[str]] = semantic.pop("by_tick")
    backgrounds = []
    for tick in sorted(STAGE_NAMES):
        # Presentations occur at VM ticks 8,18,... and are numbered 10,20,...
        capture_index = max(0, math.ceil((tick - 8) / 10))
        capture_frame = (capture_index + 1) * 10
        screen = visuals.encode_screen(
            page0[capture_index],
            palettes[capture_index],
            visual_data["attributes"][capture_index],  # type: ignore[index]
        )
        timing = live_exact["ticks"][tick]
        counters = live_instrumented["ticks"][tick]["counters"]
        trace_tick = trace_ticks[tick]
        clear_bytes = 6144 if trace_tick.get("clears_page0", 0) else 0
        construction_bytes = (
            clear_bytes + counters["background_span_bytes"] + counters["text_bytes"]
        )
        backgrounds.append(
            {
                "stage": STAGE_NAMES[tick],
                "vm_tick": tick,
                "reference_capture_frame": capture_frame,
                "run_tasks_tstates": timing["run_tasks_tstates"],
                "pal_refreshes": timing["run_tasks_refreshes"],
                "measurement_scope": "complete run_tasks tick in live-background timing build",
                "polygons": trace_tick.get("polygons_page0", 0),
                "points": trace_tick.get("points_page0", 0),
                "glyphs": trace_tick.get("glyphs_page0", 0),
                "renderer_background_primitives": counters["background_primitives"],
                "background_span_bytes": counters["background_span_bytes"],
                "background_full_fill_bytes": clear_bytes,
                "background_text_bytes": counters["text_bytes"],
                "background_bitmap_bytes_written": construction_bytes,
                "prepared_background_lzss_bytes": len(lzss.compress(screen[:6144])),
                "already_prebuilt_in_baseline": tick in CHECKPOINT_TICKS,
                "policy": "prebuild" if timing["run_tasks_refreshes"] >= 5 else "benchmark",
            }
        )

    copy_ops = semantic["copy_operations"]
    screen_to_background_ops = sum(
        count
        for route, count in copy_ops.items()
        if route in {"1->0", "2->0"}
    )
    reference_paths = list(args.reference_screens.glob("frame-*.scr"))
    output = {
        "schema": "another-spectrum-vm-baseline-v1",
        "baseline": {
            "build": "VM baseline — independent-reference fixed",
            "source_branch": "agent/polygon-sota-benchmark (descends proper-ega)",
            "snapshot": profile["snapshot"],
            "completed": profile["completed"],
            "vm_tick": profile["vm_tick"],
            "instruction_count": profile["instruction_count"],
            "trace_hash": profile["trace_hash"],
            "total_refreshes": profile["total_refreshes"],
            "total_tstates_at_refresh_boundary": profile["total_tstates_at_refresh_boundary"],
            "equivalent_seconds_at_50hz": profile["equivalent_seconds_at_50hz"],
            "retained_presentations": profile["retained_presentations"],
            "presentation_cost": profile["presentation_cost"],
            "screen_sequence_sha256": profile["screen_sequence_sha256"],
        },
        "renderer": {
            **instrumented["totals"],
            "measurement_only_visual_identity": instrumented["visual_identity"],
            "instrumentation_refreshes": instrumented["instrumented_refreshes"],
            "uninstrumented_exact_run_tasks_tstates": sum(
                item["run_tasks_tstates"] for item in exact["ticks"]
            ),
            "uninstrumented_exact_run_tasks_refreshes": sum(
                item["run_tasks_refreshes"] for item in exact["ticks"]
            ),
        },
        "bitmap": profile["bitmap"],
        "attributes": profile["attributes"],
        "page_operations": {
            "semantic_copy_counts": copy_ops,
            "screen_to_background_full_copy_operations": screen_to_background_ops,
            "screen_to_background_bitmap_bytes": screen_to_background_ops * 6144,
            "background_to_screen_actual_restore_bytes": profile["bitmap"]["background_restore_bytes"],
            "baseline_attribute_copy_bytes": profile["attributes"]["baseline_copy_bytes"],
        },
        "semantic_full_intro": semantic,
        "background_construction": backgrounds,
        "regression": {
            "reference_screens": len(reference_paths),
            "reference_screens_sha256": sha256_paths(reference_paths),
            "comparison": comparison,
        },
        "resident": {
            "snapshot_bytes": manifest["snapshot_bytes"],
            "renderer_bytes": manifest["renderer_bytes"],
            "vm_bytes": manifest["vm_bytes"],
            "bank7_payload_bytes": manifest["bank7_payload_bytes"],
            "bank7_free_bytes": manifest["bank7_free_bytes"],
            "checkpoint_stream_bytes": manifest["checkpoint_stream_bytes"],
            "page3_snapshot_stream_bytes": manifest["page3_snapshot_stream_bytes"],
            "direct_decision_bytes": manifest["direct_decision_bytes"],
            "layout": manifest["layout"],
        },
        "measurement_notes": [
            "All execution measurements use real DOS shareware bytecode, shapes and palettes.",
            "The 128K PAL frame length is 70,908 T-states.",
            "Exact tick timings have a 512-T-state polling error bound and exclude scheduler wait/setup.",
            "Instrumented counters were verified against the uninstrumented 298-screen hash sequence.",
        ],
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(output, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "out": str(args.out),
        "snapshot_sha256": output["baseline"]["snapshot"]["sha256"],
        "refreshes": output["baseline"]["total_refreshes"],
        "presentations": output["baseline"]["retained_presentations"],
        "backgrounds": len(backgrounds),
    }, indent=2))


if __name__ == "__main__":
    main()
