#!/usr/bin/env python3
"""Generate child-primitive masks and exact hot-root span templates.

The input trace is produced by generate_deep_trace.mjs.  Top-level event
liveness remains the proven draw-event mask from optimize_draws.py.  This tool
replays the same painter order at Spectrum resolution, determines which child
primitives survive sampled presentations, and packs three bank-7 data sets:
child culling only, hot-root span templates only, and both combined.
"""
from __future__ import annotations

import argparse
import json
import re
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

W, H = 256, 192
DATA_OFFSET = 0x2000
DATA_ADDRESS = 0xC000 + DATA_OFFSET
DATA_LIMIT = 0x2000


@dataclass
class Primitive:
    ident: int
    event: int
    shape: int
    color: int
    zoom: int
    x: int
    y: int
    page: int
    depth: int
    kind: str = ""
    points: list[tuple[int, int]] = field(default_factory=list)
    spans: list[tuple[int, int, int]] = field(default_factory=list)
    bbox: tuple[int, int, int, int] | None = None
    pixels: int = 0

    @property
    def vertex_count(self) -> int:
        return 1 if self.kind == "point" else len(self.points)

    @property
    def cost(self) -> int:
        # Relative renderer-work score: transform/edge work plus covered spans.
        return 80 + self.vertex_count * 70 + len(self.spans) * 95 + self.pixels // 4


@dataclass
class Event:
    ident: int
    kind: str
    page: int | None = None
    root: int | None = None
    color: int | None = None
    zoom: int | None = None
    x: int | None = None
    y: int | None = None
    tick: int = -1
    primitives: list[int] = field(default_factory=list)


@dataclass
class TraceData:
    events: dict[int, Event]
    primitives: dict[int, Primitive]
    operations: list[tuple]
    event_count: int
    primitive_count: int


def sx(value: int) -> int:
    if value < 0:
        return 0
    if value >= 320:
        return 255
    return (value - value // 5) & 0xFF


def sy(value: int) -> int:
    if value < 0:
        return 0
    if value >= 200:
        return 191
    return (value - value // 25) & 0xFF


def polygon_spans(points: list[tuple[int, int]]) -> tuple[list[tuple[int, int, int]], tuple[int, int, int, int] | None]:
    if not points:
        return [], None
    scaled = [(sx(x), sy(y)) for x, y in points]
    min_x = min(x for x, _ in scaled)
    max_x = max(x for x, _ in scaled)
    min_y = min(y for _, y in scaled)
    max_y = max(y for _, y in scaled)
    if max_y >= H:
        # The renderer has only 192 edge entries. No observed selected template
        # should reach this endpoint; reject it rather than encode a wrong one.
        return [], None

    left = [255] * H
    right = [0] * H

    def boundary(x: int, y: int) -> None:
        if not 0 <= y < H:
            return
        if x < left[y]:
            left[y] = x
        if x > right[y]:
            right[y] = x

    count = len(scaled)
    for i in range(count):
        x0, y0 = scaled[i]
        x1, y1 = scaled[(i + 1) % count]
        if y1 < y0:
            x0, x1 = x1, x0
            y0, y1 = y1, y0
        dy = y1 - y0
        if dy == 0:
            boundary(x0, y0)
            boundary(x1, y1)
            continue
        raw_dx = x1 - x0
        step = 1 if raw_dx >= 0 else -1
        dx = abs(raw_dx)
        err = 0
        x = x0
        y = y0
        while True:
            boundary(x, y)
            if y == y1:
                break
            err += dx
            while err >= dy:
                err -= dy
                x = (x + step) & 0xFF
            y += 1

    spans = [(y, left[y], right[y]) for y in range(min_y, max_y + 1) if left[y] <= right[y]]
    return spans, (min_x, max_x, min_y, max_y)


def point_spans(x: int, y: int) -> tuple[list[tuple[int, int, int]], tuple[int, int, int, int] | None]:
    px, py = sx(x), sy(y)
    if py >= H:
        return [], None
    return [(py, px, px)], (px, px, py, py)


def parse_trace(path: Path) -> TraceData:
    events: dict[int, Event] = {}
    primitives: dict[int, Primitive] = {}
    operations: list[tuple] = []
    tick = -1
    current_event = 0
    pending: tuple[int, int, int, int, int] | None = None
    vertices: list[tuple[int, int]] = []

    tick_re = re.compile(r"TRACE_TICK (\d+)")
    event_re = re.compile(r"vid_opcd_event (\d+)")
    top_re = re.compile(r"SEM top_shape event=(\d+) root=(\d+) color=(\d+) zoom=(-?\d+) x=(-?\d+) y=(-?\d+) page=(\d+)")
    prim_re = re.compile(r"SEM primitive id=(\d+) event=(\d+) shape=(\d+) color=(\d+) zoom=(-?\d+) x=(-?\d+) y=(-?\d+) page=(\d+) depth=(\d+)")
    quad_re = re.compile(r"SEM quadstrip primitive=(\d+) event=(\d+) buffer=(\d+) color=(\d+) vertices=(\d+)")
    vertex_re = re.compile(r"SEM vertex primitive=(\d+) index=\d+ x=(-?\d+) y=(-?\d+)")
    point_re = re.compile(r"SEM point primitive=(\d+) event=(\d+) buffer=(\d+) color=(\d+) x=(-?\d+) y=(-?\d+)")
    text_event_re = re.compile(r"SEM text_event event=(\d+)")
    glyph_re = re.compile(r"SEM glyph event=(\d+) buffer=(\d+) color=(\d+) char=\d+ x=(-?\d+) y=(-?\d+)")
    clear_re = re.compile(r"SEM clear buffer=(\d+) color=(\d+)")
    copy_re = re.compile(r"SEM copy dst=(\d+) src=(\d+)")
    present_re = re.compile(r"SEM present buffer=(\d+)")

    def flush() -> None:
        nonlocal pending, vertices
        if pending is None:
            return
        pid, event_id, page, color, expected = pending
        if len(vertices) != expected:
            raise RuntimeError((pid, len(vertices), expected))
        prim = primitives[pid]
        prim.kind = "polygon"
        prim.points = list(vertices)
        prim.spans, prim.bbox = polygon_spans(prim.points)
        prim.pixels = sum(right - left + 1 for _, left, right in prim.spans)
        operations.append(("primitive", pid, page, color))
        pending = None
        vertices = []

    for line in path.read_text(errors="replace").splitlines():
        match = vertex_re.search(line)
        if match:
            pid, x, y = map(int, match.groups())
            if pending is None or pending[0] != pid:
                raise RuntimeError(("orphan vertex", line))
            vertices.append((x, y))
            continue
        flush()
        match = tick_re.search(line)
        if match:
            tick = int(match.group(1))
            operations.append(("tick", tick))
            continue
        match = event_re.search(line)
        if match:
            current_event = int(match.group(1))
            events[current_event] = Event(current_event, "shape", tick=tick)
            continue
        match = text_event_re.search(line)
        if match:
            current_event = int(match.group(1))
            if current_event in events:
                raise RuntimeError(("duplicate text event", current_event))
            events[current_event] = Event(current_event, "text", tick=tick)
            operations.append(("text_event", current_event))
            continue
        match = top_re.search(line)
        if match:
            eid, root, color, zoom, x, y, page = map(int, match.groups())
            event = events[eid]
            event.page, event.root, event.color = page, root, color
            event.zoom, event.x, event.y = zoom, x, y
            current_event = eid
            continue
        match = prim_re.search(line)
        if match:
            pid, eid, shape, color, zoom, x, y, page, depth = map(int, match.groups())
            primitives[pid] = Primitive(pid, eid, shape, color, zoom, x, y, page, depth)
            events[eid].primitives.append(pid)
            continue
        match = quad_re.search(line)
        if match:
            pending = tuple(map(int, match.groups()))
            continue
        match = point_re.search(line)
        if match:
            pid, eid, page, color, x, y = map(int, match.groups())
            prim = primitives[pid]
            prim.kind = "point"
            prim.points = [(x, y)]
            prim.spans, prim.bbox = point_spans(x, y)
            prim.pixels = len(prim.spans)
            operations.append(("primitive", pid, page, color))
            continue
        match = glyph_re.search(line)
        if match:
            operations.append(("glyph", *map(int, match.groups())))
            continue
        match = clear_re.search(line)
        if match:
            operations.append(("clear", *map(int, match.groups())))
            continue
        match = copy_re.search(line)
        if match:
            operations.append(("copy", *map(int, match.groups())))
            continue
        match = present_re.search(line)
        if match:
            operations.append(("present", int(match.group(1))))
            continue
    flush()

    event_count = max(events, default=0)
    primitive_count = max(primitives, default=0)
    if event_count != 9648:
        raise RuntimeError(f"event count {event_count}")
    return TraceData(events, primitives, operations, event_count, primitive_count)


def load_event_mask(path: Path, count: int) -> set[int]:
    raw = path.read_bytes()
    live = {event for event in range(1, count + 1) if raw[(event - 1) >> 3] & (1 << ((event - 1) & 7))}
    return live


def replay(trace: TraceData, live_events: set[int]) -> tuple[set[int], dict[str, int]]:
    owners = [np.zeros((H, W), dtype=np.int32) for _ in range(4)]
    colors = [np.zeros((H, W), dtype=np.uint8) for _ in range(4)]
    live_primitives: set[int] = set()
    tick = -1
    sampled = 0

    def paint(pid: int, page: int, color: int) -> None:
        prim = trace.primitives[pid]
        if not prim.spans:
            return
        mask = np.zeros((H, W), dtype=bool)
        for y, left, right in prim.spans:
            mask[y, left : right + 1] = True
        if color == 17:
            colors[page][mask] = colors[0][mask]
        elif color == 16:
            colors[page][mask] |= 8
        else:
            colors[page][mask] = color
        owners[page][mask] = pid

    for op in trace.operations:
        kind = op[0]
        if kind == "tick":
            tick = op[1]
        elif kind == "primitive":
            _, pid, page, color = op
            event = trace.events[trace.primitives[pid].event]
            if event.ident in live_events and event.tick not in {190, 302, 403, 1053, 2211}:
                paint(pid, page, color)
        elif kind == "glyph":
            _, event, page, color, x, y = op
            if event not in live_events:
                continue
            x0 = sx(x)
            y0 = sy(y)
            x1 = min(W, x0 + 8)
            y1 = min(H, y0 + 8)
            if x0 < x1 and y0 < y1:
                colors[page][y0:y1, x0:x1] = color
                owners[page][y0:y1, x0:x1] = -event
        elif kind == "clear":
            _, page, color = op
            colors[page].fill(color)
            owners[page].fill(0)
        elif kind == "copy":
            _, dst, src = op
            colors[dst][:] = colors[src]
            owners[dst][:] = owners[src]
        elif kind == "present":
            _, page = op
            is_sample = tick == 0 or (tick >= 8 and (tick - 8) % 10 == 0)
            if is_sample:
                sampled += 1
                visible = np.unique(owners[page])
                live_primitives.update(int(value) for value in visible if value > 0)

    # Compositing primitives and every primitive in the same top-level event are
    # retained conservatively because alpha/page operations depend on prior color.
    composite_events = {
        prim.event for prim in trace.primitives.values()
        if prim.color in (16, 17)
        and prim.event in live_events
        and trace.events[prim.event].tick not in {190, 302, 403, 1053, 2211}
    }
    for event in composite_events:
        live_primitives.update(trace.events[event].primitives)

    stats = {
        "sampled_presentations": sampled,
        "live_primitives": len(live_primitives),
        "dead_primitives": trace.primitive_count - len(live_primitives),
        "composite_events_retained": len(composite_events),
    }
    return live_primitives, stats


def mask_bytes(event: Event, live_primitives: set[int]) -> bytes:
    raw = bytearray((len(event.primitives) + 7) // 8)
    if len(raw) > 159:
        raise ValueError(f"child mask too large for fixed buffer: event={event.ident} bytes={len(raw)}")
    for index, pid in enumerate(event.primitives):
        if pid in live_primitives:
            raw[index >> 3] |= 1 << (index & 7)
    # Length prefix lets the runtime copy the complete mask from bank 7 once at
    # event entry. Primitive tests then stay in uncontended fixed RAM.
    return bytes((len(raw),)) + bytes(raw)


def rle_descriptors(values: list[int]) -> bytes:
    out = bytearray()
    if not values:
        return bytes(out)
    current = values[0]
    run = 1
    for value in values[1:]:
        if value == current and run < 255:
            run += 1
            continue
        out.extend((current, run))
        current = value
        run = 1
    out.extend((current, run))
    return bytes(out)


def template_bytes(event: Event, primitives: dict[int, Primitive], live: set[int] | None) -> bytes | None:
    records: list[bytes] = []
    for pid in event.primitives:
        prim = primitives[pid]
        if live is not None and pid not in live:
            continue
        if not prim.spans or prim.bbox is None or len(prim.spans) > 255:
            continue
        min_x, max_x, min_y, max_y = prim.bbox
        if max_y >= H:
            return None
        record = bytearray((prim.color & 0xFF, min_x, max_x, min_y, max_y, len(prim.spans)))
        for y, left, right in prim.spans:
            record.extend((y, left, right))
        records.append(bytes(record))
    if not records or len(records) > 255:
        return None
    out = bytearray()
    out.extend(len(event.primitives).to_bytes(2, "little"))
    out.append(len(records))
    for record in records:
        out.extend(record)
    return bytes(out)


def pack_mode(
    mode: str,
    trace: TraceData,
    live_events: set[int],
    live_primitives: set[int],
    output: Path,
) -> dict:
    immediate_shapes = [
        event for event in trace.events.values()
        if event.ident in live_events
        and event.kind == "shape"
        and event.page != 3
        and event.tick not in {190, 302, 403, 1053, 2211}
    ]
    immediate_shapes.sort(key=lambda event: event.ident)

    child_candidates: list[tuple[float, int, bytes, int]] = []
    template_candidates: list[tuple[float, int, bytes, tuple[int, int]]] = []
    group_count = Counter((event.root or 0, event.zoom or 0) for event in immediate_shapes)

    for event in immediate_shapes:
        dead = [pid for pid in event.primitives if pid not in live_primitives]
        if dead and not any(trace.primitives[pid].color in (16, 17) for pid in event.primitives):
            payload = mask_bytes(event, live_primitives)
            benefit = sum(trace.primitives[pid].cost for pid in dead)
            child_candidates.append((benefit / max(1, len(payload) + 4), event.ident, payload, benefit))

        group = (event.root or 0, event.zoom or 0)
        if group_count[group] >= 2:
            payload = template_bytes(
                event,
                trace.primitives,
                live_primitives if mode == "both" else None,
            )
            if payload is not None:
                generic = sum(trace.primitives[pid].cost for pid in event.primitives)
                # Templates retain fill cost; score only decode/edge work and add
                # a hot-root multiplier for repeatedly used root/zoom pairs.
                benefit = sum(100 + trace.primitives[pid].vertex_count * 85 + len(trace.primitives[pid].spans) * 45 for pid in event.primitives)
                benefit *= min(group_count[group], 8)
                template_candidates.append((benefit / max(1, len(payload) + 4), event.ident, payload, group))

    child_candidates.sort(reverse=True)
    template_candidates.sort(reverse=True)

    selected_masks: dict[int, bytes] = {}
    selected_templates: dict[int, bytes] = {}
    selected_groups: Counter[tuple[int, int]] = Counter()

    def estimated_size(masks: dict[int, bytes], templates: dict[int, bytes]) -> int:
        selected = set(masks) | set(templates)
        # Use the uncompressed descriptor-event count as a safe upper bound; the
        # emitted RLE stream is always smaller or equal. Payloads are deduplicated
        # exactly as they are in the final packer.
        return (
            len(immediate_shapes)
            + 4 * (len(selected) + 1)
            + sum(len(payload) for payload in set(masks.values()))
            + sum(len(payload) for payload in set(templates.values()))
        )

    if mode == "child":
        for _, event_id, payload, _benefit in child_candidates:
            if len(selected_masks) >= 255:
                break
            selected_masks[event_id] = payload
            if estimated_size(selected_masks, selected_templates) > DATA_LIMIT:
                selected_masks.pop(event_id)

    elif mode == "template":
        for _, event_id, payload, group in template_candidates:
            if len(selected_templates) >= 255:
                break
            selected_templates[event_id] = payload
            if estimated_size(selected_masks, selected_templates) > DATA_LIMIT:
                selected_templates.pop(event_id)
                continue
            selected_groups[group] += 1

    else:
        # Start with the profitable culling set. For events that also have an
        # exact span template, replace the mask rather than adding another
        # descriptor. This keeps descriptor-run overhead at child-only levels
        # while exercising both mechanisms in the combined image.
        for _, event_id, payload, _benefit in child_candidates:
            if len(selected_masks) >= 255:
                break
            selected_masks[event_id] = payload
            if estimated_size(selected_masks, selected_templates) > DATA_LIMIT:
                selected_masks.pop(event_id)

        for _, event_id, payload, group in template_candidates:
            if event_id not in selected_masks:
                continue
            old_mask = selected_masks.pop(event_id)
            selected_templates[event_id] = payload
            if estimated_size(selected_masks, selected_templates) > DATA_LIMIT:
                selected_templates.pop(event_id)
                selected_masks[event_id] = old_mask
                continue
            selected_groups[group] += 1

    selected_events = sorted(set(selected_masks) | set(selected_templates))
    descriptor_id = {event_id: index + 1 for index, event_id in enumerate(selected_events)}
    descriptor_values = [descriptor_id.get(event.ident, 0) for event in immediate_shapes]
    stream = rle_descriptors(descriptor_values)
    table_size = 4 * (len(selected_events) + 1)
    cursor = len(stream) + table_size
    if cursor > DATA_LIMIT:
        raise RuntimeError((mode, cursor))

    payload = bytearray(cursor)
    payload[: len(stream)] = stream
    table_offset = len(stream)
    dedup: dict[tuple[str, bytes], int] = {}

    def add_payload(kind: str, data: bytes) -> int:
        nonlocal cursor
        key = (kind, data)
        if key in dedup:
            return dedup[key]
        if cursor + len(data) > DATA_LIMIT:
            raise RuntimeError(f"{mode} data overflow {cursor}+{len(data)}")
        address = DATA_ADDRESS + cursor
        payload.extend(data)
        cursor += len(data)
        dedup[key] = address
        return address

    for event_id in selected_events:
        did = descriptor_id[event_id]
        mask_ptr = add_payload("mask", selected_masks[event_id]) if event_id in selected_masks else 0
        template_ptr = add_payload("template", selected_templates[event_id]) if event_id in selected_templates else 0
        pos = table_offset + did * 4
        payload[pos : pos + 2] = mask_ptr.to_bytes(2, "little")
        payload[pos + 2 : pos + 4] = template_ptr.to_bytes(2, "little")

    blob = bytes(payload)
    if len(blob) > DATA_LIMIT:
        raise RuntimeError((mode, len(blob)))
    (output / f"deep-{mode}.bin").write_bytes(blob)
    (output / f"deep-{mode}.inc").write_text(
        "; generated by deep_optimize.py\n"
        f"DEEP_DESCRIPTOR_STREAM    EQU 0x{DATA_ADDRESS:04X}\n"
        f"DEEP_DESCRIPTOR_TABLE     EQU 0x{DATA_ADDRESS + table_offset:04X}\n",
        encoding="utf-8",
    )

    template_roots = Counter()
    for event_id in selected_templates:
        event = trace.events[event_id]
        template_roots[(event.root or 0, event.zoom or 0)] += 1

    report = {
        "mode": mode,
        "data_offset_bank7": DATA_OFFSET,
        "data_bytes": len(blob),
        "descriptor_events": len(immediate_shapes),
        "descriptor_stream_bytes": len(stream),
        "descriptor_runs": len(stream) // 2,
        "descriptor_table_bytes": table_size,
        "optimized_events": len(selected_events),
        "child_mask_events": len(selected_masks),
        "child_mask_payload_bytes": sum(len(payload) for payload in selected_masks.values()),
        "child_mask_max_bytes": max((len(payload) - 1 for payload in selected_masks.values()), default=0),
        "template_events": len(selected_templates),
        "template_unique_payloads": len({payload for payload in selected_templates.values()}),
        "template_root_zoom_groups": [
            {"root": root, "zoom": zoom, "events": count}
            for (root, zoom), count in template_roots.most_common(20)
        ],
    }
    (output / f"deep-{mode}-report.json").write_text(json.dumps(report, indent=2) + "\n")
    return report


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--trace", type=Path, required=True)
    parser.add_argument("--event-mask", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)

    trace = parse_trace(args.trace)
    live_events = load_event_mask(args.event_mask, trace.event_count)
    live_primitives, replay_stats = replay(trace, live_events)

    modes = {
        mode: pack_mode(mode, trace, live_events, live_primitives, args.out)
        for mode in ("child", "template", "both")
    }
    report = {
        "events": trace.event_count,
        "primitives": trace.primitive_count,
        "top_level_live_events": len(live_events),
        **replay_stats,
        "live_immediate_shape_events": sum(
            1 for event in trace.events.values()
            if event.ident in live_events and event.kind == "shape" and event.page != 3
        ),
        "modes": modes,
    }
    (args.out / "deep-report.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
