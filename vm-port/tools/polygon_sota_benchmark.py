import json
import math
import random
import statistics

W, H = 256, 192


def border_point(rng):
    p = rng.randrange(2 * (W + H) - 4)
    if p < W:
        return p, 0
    p -= W
    if p < H - 1:
        return W - 1, p + 1
    p -= H - 1
    if p < W - 1:
        return W - 2 - p, H - 1
    p -= W - 1
    return 0, H - 2 - p


def blank_counts():
    return {
        key: 0
        for key in (
            "clear", "boundary", "err_add", "xstep", "table_read",
            "dda_scan", "dda_add", "bytes_tested", "stores",
            "changed", "preproc_records"
        )
    }


def bres_edge(a, b, left, right, counts):
    x0, y0 = a
    x1, y1 = b
    if y1 < y0:
        x0, y0, x1, y1 = x1, y1, x0, y0

    dy = y1 - y0
    if dy == 0:
        for x in (x0, x1):
            left[y0] = min(left[y0], x)
            right[y0] = max(right[y0], x)
            counts["boundary"] += 1
        return

    dx = abs(x1 - x0)
    sx = 1 if x1 >= x0 else -1
    err = 0
    x, y = x0, y0

    while True:
        left[y] = min(left[y], x)
        right[y] = max(right[y], x)
        counts["boundary"] += 1
        if y == y1:
            break
        err += dx
        counts["err_add"] += 1
        while err >= dy:
            err -= dy
            x += sx
            counts["xstep"] += 1
        y += 1


def baseline_spans(poly, counts):
    ys = [p[1] for p in poly]
    low = max(0, min(ys))
    high = min(H - 1, max(ys))
    left = [255] * H
    right = [0] * H
    counts["clear"] += 2 * (high - low + 1)

    for i in range(len(poly)):
        bres_edge(poly[i], poly[(i + 1) % len(poly)], left, right, counts)

    spans = []
    for y in range(low, high + 1):
        counts["table_read"] += 2
        if left[y] <= right[y]:
            spans.append((y, left[y], right[y]))
    return spans


def dda_edge(a, b, counts, fraction_bits=8):
    """Approximate signed fixed-point DDA.

    Deliberately does not preserve the current Bresenham edge convention.
    Raster differences are measured rather than treated as benchmark failure.
    """
    x0, y0 = a
    x1, y1 = b
    if y1 < y0:
        x0, y0, x1, y1 = x1, y1, x0, y0

    dy = y1 - y0
    if dy == 0:
        return {y0: (min(x0, x1), max(x0, x1))}

    scale = 1 << fraction_bits
    step = ((x1 - x0) * scale) // dy
    x_fixed = x0 * scale
    samples = {}

    for y in range(y0, y1 + 1):
        x = x_fixed // scale
        samples[y] = (x, x)
        x_fixed += step
        counts["dda_add"] += 1

    return samples


def dda_spans(poly, counts):
    rows = {}
    for i in range(len(poly)):
        samples = dda_edge(poly[i], poly[(i + 1) % len(poly)], counts)
        for y, (low, high) in samples.items():
            counts["boundary"] += 1
            if y in rows:
                old_low, old_high = rows[y]
                rows[y] = min(old_low, low), max(old_high, high)
            else:
                rows[y] = low, high

    spans = []
    for y in sorted(rows):
        left, right = rows[y]
        if 0 <= y < H and left <= right:
            spans.append((y, max(0, left), min(W - 1, right)))
            counts["dda_scan"] += 1
    return spans


def render(spans, framebuffer, postdraw, counts):
    changed_masks = []
    for y, left, right in spans:
        first_byte = left >> 3
        last_byte = right >> 3

        for byte_x in range(first_byte, last_byte + 1):
            left_mask = 0xFF >> (left & 7) if byte_x == first_byte else 0xFF
            right_mask = (
                (0xFF << (7 - (right & 7))) & 0xFF
                if byte_x == last_byte
                else 0xFF
            )
            mask = left_mask & right_mask
            index = y * 32 + byte_x
            old = framebuffer[index]
            new = old | mask
            counts["bytes_tested"] += 1

            if new != old:
                changed_masks.append((index, new ^ old))

            if postdraw and new == old:
                continue

            framebuffer[index] = new
            counts["stores"] += 1
            if new != old:
                counts["changed"] += 1

    return changed_masks


def apply_preprocessed(changes, framebuffer, counts):
    """Replay offline post-draw changed-byte records."""
    for index, mask in changes:
        old = framebuffer[index]
        new = old | mask
        counts["preproc_records"] += 1
        if new == old:
            continue
        framebuffer[index] = new
        counts["stores"] += 1
        counts["changed"] += 1


def modeled_tstates(counts, mode):
    """Relative Z80 cost model; not emulator timing."""
    if mode == "baseline":
        return (
            counts["clear"] * 21
            + counts["boundary"] * 45
            + counts["err_add"] * 24
            + counts["xstep"] * 36
            + counts["table_read"] * 18
            + counts["bytes_tested"] * 30
            + counts["stores"] * 12
        )
    if mode == "dda":
        return (
            counts["boundary"] * 18
            + counts["dda_add"] * 20
            + counts["dda_scan"] * 14
            + counts["bytes_tested"] * 30
            + counts["stores"] * 12
        )
    if mode == "preprocessed":
        return counts["preproc_records"] * 18 + counts["stores"] * 12
    raise ValueError(mode)


def run(seed=1, triangles=5000):
    rng = random.Random(seed)
    samples = {name: [] for name in ("baseline", "dda", "dda_post", "preprocessed")}
    pixel_differences = []
    byte_differences = []
    exact = 0

    for _ in range(triangles):
        poly = [border_point(rng) for _ in range(3)]
        center_x = sum(x for x, _ in poly) / 3
        center_y = sum(y for _, y in poly) / 3
        poly.sort(key=lambda p: math.atan2(p[1] - center_y, p[0] - center_x))

        baseline_counts = blank_counts()
        dda_counts = blank_counts()
        post_counts = blank_counts()
        pre_counts = blank_counts()

        baseline = baseline_spans(poly, baseline_counts)
        dda = dda_spans(poly, dda_counts)

        baseline_fb = bytearray(6144)
        dda_fb = bytearray(6144)
        render(baseline, baseline_fb, False, baseline_counts)
        changes = render(dda, dda_fb, False, dda_counts)

        post_fb = bytearray(6144)
        render(dda, post_fb, False, post_counts)
        render(dda, post_fb, True, post_counts)

        pre_fb = bytearray(6144)
        apply_preprocessed(changes, pre_fb, pre_counts)
        apply_preprocessed(changes, pre_fb, pre_counts)

        pixel_diff = sum((a ^ b).bit_count() for a, b in zip(baseline_fb, dda_fb))
        byte_diff = sum(a != b for a, b in zip(baseline_fb, dda_fb))
        pixel_differences.append(pixel_diff)
        byte_differences.append(byte_diff)
        exact += baseline_fb == dda_fb

        samples["baseline"].append(modeled_tstates(baseline_counts, "baseline"))
        samples["dda"].append(modeled_tstates(dda_counts, "dda"))
        samples["dda_post"].append(modeled_tstates(post_counts, "dda"))
        samples["preprocessed"].append(modeled_tstates(pre_counts, "preprocessed"))

    result = {
        "seed": seed,
        "triangles": triangles,
        "exact_framebuffers": exact,
        "visual_difference": {
            "mean_pixels": statistics.mean(pixel_differences),
            "median_pixels": statistics.median(pixel_differences),
            "p95_pixels": statistics.quantiles(pixel_differences, n=20)[18],
            "mean_bytes": statistics.mean(byte_differences),
        },
        "modes": {},
    }

    for name, values in samples.items():
        result["modes"][name] = {
            "mean_modeled_t": statistics.mean(values),
            "median_modeled_t": statistics.median(values),
            "p95_modeled_t": statistics.quantiles(values, n=20)[18],
        }

    baseline_mean = result["modes"]["baseline"]["mean_modeled_t"]
    dda_mean = result["modes"]["dda"]["mean_modeled_t"]
    result["speedup_dda_vs_baseline"] = baseline_mean / dda_mean
    result["speedup_repeated_dda_postdraw"] = (
        2 * dda_mean / result["modes"]["dda_post"]["mean_modeled_t"]
    )
    result["speedup_repeated_preprocessed"] = (
        2 * dda_mean / result["modes"]["preprocessed"]["mean_modeled_t"]
    )
    return result


if __name__ == "__main__":
    print(json.dumps(run(), indent=2))
