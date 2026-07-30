#!/usr/bin/env python3
"""Create exact 268/298 (4.497 fps) retained-frame plans from a baseline profile."""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

SAMPLES = 298
DROP_COUNT = 30


def tick_for_slot(slot: int) -> int:
    return 8 + (slot - 1) * 10


def make_plan(name: str, drops: list[int], profile: dict) -> dict:
    drops = sorted(drops)
    drop_set = set(drops)
    keep = [x for x in range(1, SAMPLES + 1) if x not in drop_set]
    by_slot = {int(f['presentation']): f for f in profile['frames']}
    return {
        'name': name,
        'nominal_fps': len(keep) / (2980 / 50),
        'drop_slots': drops,
        'drop_ticks': [tick_for_slot(x) for x in drops],
        'keep_slots': keep,
        'keep_ticks': [tick_for_slot(x) for x in keep],
        'estimated_dropped_refreshes': sum(int(by_slot[x]['host_refreshes']) for x in drops),
        'estimated_dropped_changed_pixels': sum(int(by_slot[x]['visible_changed_pixels']) for x in drops),
    }


def select_greedy(frames: list[dict], score, count: int = DROP_COUNT) -> list[int]:
    candidates = sorted(
        (f for f in frames if 1 < int(f['presentation']) < SAMPLES),
        key=score,
        reverse=True,
    )
    chosen: set[int] = set()
    for frame in candidates:
        slot = int(frame['presentation'])
        if slot - 1 in chosen or slot + 1 in chosen:
            continue
        chosen.add(slot)
        if len(chosen) == count:
            break
    if len(chosen) < count:
        for frame in candidates:
            slot = int(frame['presentation'])
            if slot in chosen:
                continue
            chosen.add(slot)
            if len(chosen) == count:
                break
    if len(chosen) != count:
        raise RuntimeError(f'only selected {len(chosen)} drops')
    return sorted(chosen)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument('profile', type=Path)
    ap.add_argument('out_dir', type=Path)
    args = ap.parse_args()
    profile = json.loads(args.profile.read_text())
    frames = profile['frames']
    if len(frames) != SAMPLES:
        raise RuntimeError(f'expected {SAMPLES} frames, got {len(frames)}')

    uniform = sorted({round((k + 0.5) * SAMPLES / DROP_COUNT) for k in range(DROP_COUNT)})
    if len(uniform) != DROP_COUNT or uniform[0] <= 1 or uniform[-1] >= SAMPLES:
        raise RuntimeError(uniform)

    cost = select_greedy(frames, lambda f: (int(f['host_refreshes']), -int(f['visible_changed_pixels'])))
    balanced = select_greedy(
        frames,
        lambda f: int(f['host_refreshes']) / (1.0 + math.sqrt(max(0, int(f['visible_changed_pixels']))) / 32.0),
    )

    plans = [
        make_plan('uniform-4p5', uniform, profile),
        make_plan('cost-4p5', cost, profile),
        make_plan('balanced-4p5', balanced, profile),
    ]
    args.out_dir.mkdir(parents=True, exist_ok=True)
    for plan in plans:
        (args.out_dir / f"{plan['name']}.json").write_text(json.dumps(plan, indent=2) + '\n')
    (args.out_dir / 'rt45-plans.json').write_text(json.dumps({'plans': plans}, indent=2) + '\n')
    print(json.dumps({'plans': plans}, indent=2))


if __name__ == '__main__':
    main()
