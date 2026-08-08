#!/usr/bin/env python3
"""Build current child-culling and EGA-inspired benchmark variants."""
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
    return 49183 + [1, 3, 4, 6, 7].index(bank) * 0x4000


def inject(snapshot: bytes, bank: int, offset: int, payload: bytes, label: str) -> bytes:
    if not 0 <= offset <= 0x4000 - len(payload):
        raise RuntimeError(f"{label} bank overflow {offset:#x}+{len(payload):#x}")
    result = bytearray(snapshot)
    start = snapshot_bank_offset(bank) + offset
    result[start:start + len(payload)] = payload
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

    helper = load_module(args.helper.resolve(), "ega_minimal_helper")
    load_module(source / "st_renderer_patch.py", "st_renderer_patch_base")
    viewport = load_module(source / "viewport_renderer_patch.py", "ega_viewport_patch")
    deep = load_module(source / "deep_source_patch.py", "ega_deep_patch")
    ega = load_module(source / "ega_renderer_patch.py", "ega_renderer_patch")
    lzss = load_module(source / "lzss.py", "ega_lzss")

    bytecode, shapes, palette = helper.extract_js_resources(args.resource_js.resolve())
    if (len(bytecode), len(shapes), len(palette)) != (9842, 65156, 2048):
        raise RuntimeError((len(bytecode), len(shapes), len(palette)))

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

    old_viewport = os.environ.get("AW_VIEWPORT")
    old_fast = os.environ.get("AW_FAST_DEGENERATE")
    os.environ["AW_VIEWPORT"] = "256x192"
    os.environ["AW_FAST_DEGENERATE"] = "1"
    try:
        coordinate_tables = viewport.viewport_tables()
        winning = viewport.patch_renderer((work / "renderer_full.asm").read_text())
    finally:
        if old_viewport is None:
            os.environ.pop("AW_VIEWPORT", None)
        else:
            os.environ["AW_VIEWPORT"] = old_viewport
        if old_fast is None:
            os.environ.pop("AW_FAST_DEGENERATE", None)
        else:
            os.environ["AW_FAST_DEGENERATE"] = old_fast

    deep_renderer_text = deep.patch_renderer(winning)
    deep_vm_base = deep.patch_vm((work / "vm_full.asm").read_text())
    layout_text = (args.deep_data / "deep-child.inc").read_text()
    (work / "deep_layout.inc").write_text(layout_text)
    child_blob = (args.deep_data / "deep-child.bin").read_bytes()

    variants = ("current", "restore", "stack", "both", "profile")
    manifest: dict[str, object] = {
        "mode": "child-culling winner plus EGA-inspired framebuffer experiments",
        "variants": {},
        "resource_sizes": {"bytecode": len(bytecode), "shapes": len(shapes), "palette": len(palette)},
        "coordinate_table_bytes": len(coordinate_tables),
        "child_data_bytes": len(child_blob),
        "event_runs_bytes": len(event_runs),
        "bank7_base_end": addresses["BANK7_END"],
    }

    for mode in variants:
        patch_mode = "current" if mode == "current" else mode
        renderer_text = deep_renderer_text
        vm_text = deep_vm_base
        if mode != "current":
            renderer_text = ega.patch_renderer(renderer_text, mode)
            vm_text = ega.patch_vm(vm_text, mode)

        renderer_source = work / f"renderer-{mode}.asm"
        vm_source = work / f"vm-{mode}.asm"
        renderer_source.write_text(renderer_text)
        vm_source.write_text(vm_text)
        normalize_local_labels(renderer_source)
        normalize_local_labels(vm_source)
        renderer = helper.assemble(args.sjasmplus, renderer_source, out / f"renderer-{mode}.bin")
        vm = helper.assemble(args.sjasmplus, vm_source, out / f"vm-{mode}.bin")
        snapshot = helper.make_snapshot(
            vm, renderer, bytecode, shapes,
            packed_attrs, packed_bitmaps, checkpoints,
            palette_tables, decisions, event_runs,
        )
        snapshot = inject(snapshot, 2, viewport.TABLE_BANK2_OFFSET, coordinate_tables, "coordinate tables")
        snapshot = inject(snapshot, 7, 0x2000, child_blob, "child data")
        (out / f"{mode}.sna").write_bytes(snapshot)
        renderer_end = helper.RENDERER_OFFSET_BANK5 + len(renderer)
        manifest["variants"][mode] = {
            "vm_bytes": len(vm),
            "renderer_bytes": len(renderer),
            "renderer_gap_remaining": helper.EVENT_RUNS_OFFSET_BANK5 - renderer_end,
        }

    (out / "ega-build-manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    print(json.dumps(manifest, indent=2))


if __name__ == "__main__":
    main()
