#!/usr/bin/env python3
"""Build the current renderer and child/template/both deep variants."""
from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
from pathlib import Path


def load_module(path: Path, name: str):
    import importlib.util
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


def snapshot_bank_offset(bank: int) -> int:
    if bank == 5:
        return 27
    if bank == 2:
        return 27 + 0x4000
    if bank == 0:
        return 27 + 0x8000
    order = [1, 3, 4, 6, 7]
    return 49183 + order.index(bank) * 0x4000


def inject(snapshot: bytes, bank: int, offset: int, payload: bytes, label: str) -> bytes:
    if not 0 <= offset <= 0x4000 - len(payload):
        raise RuntimeError(f"{label} bank overflow {offset:#x}+{len(payload):#x}")
    result = bytearray(snapshot)
    start = snapshot_bank_offset(bank) + offset
    result[start : start + len(payload)] = payload
    return bytes(result)


def normalize_local_labels(path: Path) -> None:
    import re
    text = path.read_text(encoding="utf-8")
    text = re.sub(r"(?m)^\s+(\.[A-Za-z_][A-Za-z0-9_]*:)\s*$", r"\1", text)
    path.write_text(text, encoding="utf-8")


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--source-dir", type=Path, required=True)
    p.add_argument("--helper", type=Path, required=True)
    p.add_argument("--resource-js", type=Path, required=True)
    p.add_argument("--event-runs", type=Path, required=True)
    p.add_argument("--deep-data", type=Path, required=True)
    p.add_argument("--sjasmplus", type=Path, required=True)
    p.add_argument("--out", type=Path, required=True)
    args = p.parse_args()

    source = args.source_dir.resolve()
    out = args.out.resolve()
    work = out / "work"
    out.mkdir(parents=True, exist_ok=True)
    shutil.rmtree(work, ignore_errors=True)
    work.mkdir()

    helper = load_module(args.helper.resolve(), "deep_minimal_helper")
    base_patch = load_module(source / "st_renderer_patch.py", "st_renderer_patch_base")
    viewport = load_module(source / "viewport_renderer_patch.py", "viewport_renderer_patch")
    deep_patch = load_module(source / "deep_source_patch.py", "deep_source_patch")

    bytecode, shapes, palette = helper.extract_js_resources(args.resource_js.resolve())
    if (len(bytecode), len(shapes), len(palette)) != (9842, 65156, 2048):
        raise RuntimeError((len(bytecode), len(shapes), len(palette)))

    lzss = load_module(source / "lzss.py", "deep_lzss")
    attr = bytes([0x47]) * 768
    bitmap = bytes(6912)
    packed_attrs = [lzss.compress(attr), lzss.compress(attr), lzss.compress(attr)]
    packed_bitmaps = [lzss.compress(bitmap), lzss.compress(bitmap), lzss.compress(bitmap)]
    checkpoints = [lzss.compress(bytes(6144)) for _ in range(5)]
    addresses = helper.write_layout(work, packed_attrs, packed_bitmaps, checkpoints)

    for name in ("vm_full.asm", "renderer_full.asm"):
        shutil.copy2(source / name, work / name)
        normalize_local_labels(work / name)

    event_runs = args.event_runs.read_bytes()
    palette_tables = bytes(64) + bytes(range(16))
    decisions = helper.spectrum_decisions()

    # Winning full-viewport renderer: ST spans + lookup tables + collapsed paths.
    old_viewport = os.environ.get("AW_VIEWPORT")
    old_fast = os.environ.get("AW_FAST_DEGENERATE")
    os.environ["AW_VIEWPORT"] = "256x192"
    os.environ["AW_FAST_DEGENERATE"] = "1"
    try:
        coordinate_tables = viewport.viewport_tables()
        winning_source = viewport.patch_renderer((work / "renderer_full.asm").read_text(encoding="utf-8"))
    finally:
        if old_viewport is None:
            os.environ.pop("AW_VIEWPORT", None)
        else:
            os.environ["AW_VIEWPORT"] = old_viewport
        if old_fast is None:
            os.environ.pop("AW_FAST_DEGENERATE", None)
        else:
            os.environ["AW_FAST_DEGENERATE"] = old_fast

    current_renderer_source = work / "renderer-current.asm"
    current_renderer_source.write_text(winning_source, encoding="utf-8")
    normalize_local_labels(current_renderer_source)
    current_renderer = helper.assemble(args.sjasmplus, current_renderer_source, out / "renderer-current.bin")
    current_vm = helper.assemble(args.sjasmplus, work / "vm_full.asm", out / "vm-current.bin")

    current_snapshot = helper.make_snapshot(
        current_vm, current_renderer, bytecode, shapes,
        packed_attrs, packed_bitmaps, checkpoints,
        palette_tables, decisions, event_runs,
    )
    current_snapshot = inject(
        current_snapshot, 2, viewport.TABLE_BANK2_OFFSET, coordinate_tables, "coordinate tables"
    )
    (out / "current.sna").write_bytes(current_snapshot)

    deep_renderer_source = work / "renderer-deep.asm"
    deep_renderer_source.write_text(deep_patch.patch_renderer(winning_source), encoding="utf-8")
    normalize_local_labels(deep_renderer_source)
    deep_renderer = helper.assemble(args.sjasmplus, deep_renderer_source, out / "renderer-deep.bin")

    mode_manifests: dict[str, dict] = {}
    for mode in ("child", "template", "both"):
        layout_text = (args.deep_data / f"deep-{mode}.inc").read_text(encoding="utf-8")
        (work / "deep_layout.inc").write_text(layout_text, encoding="utf-8")
        deep_vm_source = work / f"vm-{mode}.asm"
        deep_vm_source.write_text(
            deep_patch.patch_vm((work / "vm_full.asm").read_text(encoding="utf-8")),
            encoding="utf-8",
        )
        normalize_local_labels(deep_vm_source)
        deep_vm = helper.assemble(args.sjasmplus, deep_vm_source, out / f"vm-{mode}.bin")
        blob = (args.deep_data / f"deep-{mode}.bin").read_bytes()
        snapshot = helper.make_snapshot(
            deep_vm, deep_renderer, bytecode, shapes,
            packed_attrs, packed_bitmaps, checkpoints,
            palette_tables, decisions, event_runs,
        )
        snapshot = inject(snapshot, 2, viewport.TABLE_BANK2_OFFSET, coordinate_tables, "coordinate tables")
        snapshot = inject(snapshot, 7, 0x2000, blob, f"deep {mode} data")
        (out / f"{mode}.sna").write_bytes(snapshot)
        mode_report = json.loads((args.deep_data / f"deep-{mode}-report.json").read_text())
        mode_manifests[mode] = {
            **mode_report,
            "vm_bytes": len(deep_vm),
            "renderer_bytes": len(deep_renderer),
        }


    renderer_end = helper.RENDERER_OFFSET_BANK5 + len(deep_renderer)
    manifest = {
        "mode": "real DOS bytecode/shapes, top-level ownership, neutral visual assets",
        "resource_sizes": {"bytecode": len(bytecode), "shapes": len(shapes), "palette": len(palette)},
        "current": {
            "vm_bytes": len(current_vm),
            "renderer_bytes": len(current_renderer),
        },
        "deep": {
            "renderer_bytes": len(deep_renderer),
            "renderer_growth_from_current": len(deep_renderer) - len(current_renderer),
            "renderer_gap_remaining": helper.EVENT_RUNS_OFFSET_BANK5 - renderer_end,
            "coordinate_table_bytes": len(coordinate_tables),
            "modes": mode_manifests,
        },
        "event_runs_bytes": len(event_runs),
        "bank7_base_end": addresses["BANK7_END"],
    }
    if manifest["deep"]["renderer_gap_remaining"] < 0:
        raise RuntimeError(manifest)
    (out / "deep-build-manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    print(json.dumps(manifest, indent=2))


if __name__ == "__main__":
    main()
