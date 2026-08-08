#!/usr/bin/env python3
"""Assemble trace and final-performance variants from an EGA benchmark workdir."""
from __future__ import annotations

import argparse
import importlib.util
import json
import re
import shutil
import subprocess
from pathlib import Path

BANK7_SCRIPT_OFFSET = 0x2600
VM_OFFSET_BANK2 = 0
RENDERER_OFFSET_BANK5 = 0x1D20
EVENT_RUNS_OFFSET_BANK5 = 0x2C00


def snapshot_bank_offset(bank: int) -> int:
    if bank == 5:
        return 27
    if bank == 2:
        return 27 + 0x4000
    if bank == 0:
        return 27 + 0x8000
    return 49183 + [1, 3, 4, 6, 7].index(bank) * 0x4000


def inject(snapshot: bytes, bank: int, offset: int, payload: bytes, label: str) -> bytes:
    if offset < 0 or offset + len(payload) > 0x4000:
        raise RuntimeError(f"{label} overflow {offset:#x}+{len(payload):#x}")
    out = bytearray(snapshot)
    pos = snapshot_bank_offset(bank) + offset
    out[pos:pos+len(payload)] = payload
    return bytes(out)


def load_module(path: Path):
    spec = importlib.util.spec_from_file_location("final_perf_patch", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def normalize_local_labels(path: Path) -> None:
    text = path.read_text()
    text = re.sub(r"(?m)^\s+(\.[A-Za-z_][A-Za-z0-9_]*:)\s*$", r"\1", text)
    path.write_text(text)


def assemble(sjasmplus: Path, source: Path, output: Path) -> bytes:
    subprocess.run([str(sjasmplus), f"--raw={output}", source.name], cwd=source.parent, check=True)
    return output.read_bytes()


def build_one(*, patch, work: Path, sjasmplus: Path, out: Path, baseline: bytes,
              label: str, vm_kwargs: dict, renderer_kwargs: dict,
              bank7_payload: bytes | None) -> dict:
    vm_text = patch.patch_vm((work / "vm-restore.asm").read_text(), **vm_kwargs)
    renderer_text = patch.patch_renderer((work / "renderer-restore.asm").read_text(), **renderer_kwargs)
    vm_src = work / f"vm-final-{label}.asm"
    renderer_src = work / f"renderer-final-{label}.asm"
    vm_src.write_text(vm_text)
    renderer_src.write_text(renderer_text)
    normalize_local_labels(vm_src)
    normalize_local_labels(renderer_src)
    vm = assemble(sjasmplus, vm_src, out / f"vm-{label}.bin")
    renderer = assemble(sjasmplus, renderer_src, out / f"renderer-{label}.bin")
    if RENDERER_OFFSET_BANK5 + len(renderer) > EVENT_RUNS_OFFSET_BANK5:
        raise RuntimeError(f"{label}: renderer overlaps event stream: {len(renderer)}")
    sna = inject(baseline, 2, VM_OFFSET_BANK2, vm, f"{label} VM")
    sna = inject(sna, 5, RENDERER_OFFSET_BANK5, renderer, f"{label} renderer")
    if bank7_payload is not None:
        sna = inject(sna, 7, BANK7_SCRIPT_OFFSET, bank7_payload, f"{label} bank7 payload")
    (out / f"{label}.sna").write_bytes(sna)
    return {
        "vm_bytes": len(vm),
        "renderer_bytes": len(renderer),
        "renderer_gap_remaining": EVENT_RUNS_OFFSET_BANK5 - (RENDERER_OFFSET_BANK5 + len(renderer)),
        "snapshot_bytes": len(sna),
        "bank7_payload_bytes": len(bank7_payload or b""),
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("command", choices=["trace", "variants", "replace-script"])
    ap.add_argument("--work", type=Path, required=True)
    ap.add_argument("--patch", type=Path, required=True)
    ap.add_argument("--sjasmplus", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--script", type=Path)
    ap.add_argument("--snapshot", type=Path)
    ap.add_argument("--output", type=Path)
    args = ap.parse_args()
    out = args.out.resolve(); out.mkdir(parents=True, exist_ok=True)
    work = args.work.resolve(); patch = load_module(args.patch.resolve())
    sjasmplus = args.sjasmplus.resolve()

    if args.command == "replace-script":
        if not args.script or not args.snapshot or not args.output:
            raise SystemExit("replace-script needs --script --snapshot --output")
        payload = patch.row_address_table() + args.script.read_bytes()
        result = inject(args.snapshot.read_bytes(), 7, BANK7_SCRIPT_OFFSET, payload, "replacement script")
        args.output.write_bytes(result)
        return

    baseline_restore = (out / "restore.sna").read_bytes()
    manifest: dict[str, object] = {"variants": {}}
    if args.command == "trace":
        info = build_one(
            patch=patch, work=work, sjasmplus=sjasmplus, out=out,
            baseline=baseline_restore, label="final-trace",
            vm_kwargs={"trace": True}, renderer_kwargs={}, bank7_payload=None,
        )
        manifest["variants"]["final-trace"] = info
    else:
        if not args.script:
            raise SystemExit("variants needs --script")
        script = args.script.read_bytes()
        payload = patch.row_address_table() + script
        if len(payload) > 0x4000 - BANK7_SCRIPT_OFFSET:
            raise RuntimeError(f"bank7 final data overflow: {len(payload)}")
        specs = {
            "script-arith": ({"script": True}, {}),
            "script-table": ({"script": True, "address_table": True}, {}),
            "script-table-ldi": ({"script": True, "address_table": True, "ldi": True}, {}),
            "script-table-ldi-lazy": ({"script": True, "address_table": True, "ldi": True}, {"lazy": True}),
            "combined": ({"script": True, "address_table": True, "ldi": True}, {"lazy": True, "full_fill": True}),
        }
        for label, (vmkw, rkw) in specs.items():
            manifest["variants"][label] = build_one(
                patch=patch, work=work, sjasmplus=sjasmplus, out=out,
                baseline=baseline_restore, label=label,
                vm_kwargs=vmkw, renderer_kwargs=rkw, bank7_payload=payload,
            )
        shutil.copy2(out / "both.sna", out / "ega-best.sna")
        manifest["row_address_table_bytes"] = len(patch.row_address_table())
        manifest["restore_script_bytes"] = len(script)
        manifest["bank7_payload_bytes"] = len(payload)
    (out / f"final-{args.command}-build-manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    print(json.dumps(manifest, indent=2))


if __name__ == "__main__":
    main()
