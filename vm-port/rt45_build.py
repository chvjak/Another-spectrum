#!/usr/bin/env python3
"""Build 4.5 fps variants by injecting a new VM, event ownership stream and drop list."""
from __future__ import annotations

import argparse
import importlib.util
import json
import re
import shutil
import subprocess
from pathlib import Path

VM_OFFSET_BANK2 = 0
EVENT_RUNS_OFFSET_BANK5 = 0x2C00
DROP_LIST_OFFSET_BANK5 = 0x1C9B
DROP_LIST_CAPACITY = 0x1CFF - DROP_LIST_OFFSET_BANK5


def bank_offset(bank: int) -> int:
    if bank == 5:
        return 27
    if bank == 2:
        return 27 + 0x4000
    if bank == 0:
        return 27 + 0x8000
    return 49183 + [1, 3, 4, 6, 7].index(bank) * 0x4000


def inject(sna: bytes, bank: int, offset: int, data: bytes, label: str) -> bytes:
    if offset < 0 or offset + len(data) > 0x4000:
        raise RuntimeError(f'{label} overflow {offset:#x}+{len(data):#x}')
    out = bytearray(sna)
    pos = bank_offset(bank) + offset
    out[pos:pos + len(data)] = data
    return bytes(out)


def load(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def normalize(path: Path) -> None:
    text = path.read_text()
    text = re.sub(r'(?m)^\s+(\.[A-Za-z_][A-Za-z0-9_]*:)\s*$', r'\1', text)
    path.write_text(text)


def assemble(sjasm: Path, source: Path, output: Path) -> bytes:
    subprocess.run([str(sjasm), f'--raw={output}', source.name], cwd=source.parent, check=True)
    return output.read_bytes()


def drop_payload(ticks: list[int]) -> bytes:
    payload = bytearray()
    for tick in ticks:
        payload += int(tick).to_bytes(2, 'little')
    payload += b'\xff\xff'
    if len(payload) > DROP_LIST_CAPACITY:
        raise RuntimeError(f'drop list {len(payload)} > {DROP_LIST_CAPACITY}')
    payload += b'\xff' * (DROP_LIST_CAPACITY - len(payload))
    return bytes(payload)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument('--base-sna', type=Path, required=True)
    ap.add_argument('--vm-source', type=Path, required=True)
    ap.add_argument('--unrolled-patch', type=Path, required=True)
    ap.add_argument('--rt45-patch', type=Path, required=True)
    ap.add_argument('--sjasmplus', type=Path, required=True)
    ap.add_argument('--plans-dir', type=Path, required=True)
    ap.add_argument('--out', type=Path, required=True)
    args = ap.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)

    unrolled = load(args.unrolled_patch, 'rt45_unrolled_patch')
    rt45 = load(args.rt45_patch, 'rt45_patch')
    base = args.base_sna.read_bytes()
    source = args.vm_source.read_text()
    source = unrolled.patch_vm(source, w1='unrolled')
    source = rt45.patch_vm(source)
    vm_src = args.out / 'vm-rt45.asm'
    vm_src.write_text(source)
    normalize(vm_src)
    layout = args.vm_source.parent / 'deep_layout.inc'
    if not layout.exists():
        raise RuntimeError(f'missing generated include: {layout}')
    shutil.copy2(layout, args.out / 'deep_layout.inc')
    vm = assemble(args.sjasmplus, vm_src, args.out / 'vm-rt45.bin')

    manifest: dict[str, object] = {
        'base_snapshot': str(args.base_sna),
        'vm_bytes': len(vm),
        'vm_gap_remaining': 0x1300 - len(vm),
        'drop_list_offset_bank5': DROP_LIST_OFFSET_BANK5,
        'event_runs_offset_bank5': EVENT_RUNS_OFFSET_BANK5,
        'variants': {},
    }
    if len(vm) > 0x1300:
        raise RuntimeError(f'VM overlaps variables by {len(vm)-0x1300} bytes')

    for plan_path in sorted(args.plans_dir.glob('*-4p5.json')):
        plan = json.loads(plan_path.read_text())
        name = plan['name']
        event_runs_path = args.plans_dir / name / 'event-runs.bin'
        event_runs = event_runs_path.read_bytes()
        if len(event_runs) > 0x3400 - EVENT_RUNS_OFFSET_BANK5:
            raise RuntimeError(f'{name}: event runs too large: {len(event_runs)}')
        sna = inject(base, 2, VM_OFFSET_BANK2, vm, f'{name} VM')
        sna = inject(sna, 5, EVENT_RUNS_OFFSET_BANK5, event_runs, f'{name} event runs')
        sna = inject(sna, 5, DROP_LIST_OFFSET_BANK5, drop_payload(plan['drop_ticks']), f'{name} drops')
        out_path = args.out / f'{name}.sna'
        out_path.write_bytes(sna)
        manifest['variants'][name] = {
            'snapshot_bytes': len(sna),
            'event_runs_bytes': len(event_runs),
            'drop_count': len(plan['drop_ticks']),
            'kept_frames': len(plan['keep_slots']),
            'nominal_fps': plan['nominal_fps'],
        }

    (args.out / 'rt45-build-manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')
    print(json.dumps(manifest, indent=2))


if __name__ == '__main__':
    main()
