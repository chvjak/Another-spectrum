import random, statistics, json, math

W, H = 256, 192


def border_point(r):
    p = r.randrange(2 * (W + H) - 4)
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


def bres_edge(a, b, left, right, c):
    x0, y0 = a
    x1, y1 = b
    if y1 < y0:
        x0, y0, x1, y1 = x1, y1, x0, y0
    dy = y1 - y0
    if dy == 0:
        for x in (x0, x1):
            left[y0] = min(left[y0], x)
            right[y0] = max(right[y0], x)
            c['boundary'] += 1
        return
    dx = abs(x1 - x0)
    sx = 1 if x1 >= x0 else -1
    err = 0
    x, y = x0, y0
    while True:
        left[y] = min(left[y], x)
        right[y] = max(right[y], x)
        c['boundary'] += 1
        if y == y1:
            break
        err += dx
        c['err_add'] += 1
        while err >= dy:
            err -= dy
            x += sx
            c['xstep'] += 1
        y += 1


def baseline_spans(poly, c):
    ys = [p[1] for p in poly]
    lo, hi = max(0, min(ys)), min(H - 1, max(ys))
    left = [255] * H
    right = [0] * H
    c['clear'] += 2 * (hi - lo + 1)
    for i in range(len(poly)):
        bres_edge(poly[i], poly[(i + 1) % len(poly)], left, right, c)
    out = []
    for y in range(lo, hi + 1):
        c['table_read'] += 2
        if left[y] <= right[y]:
            out.append((y, left[y], right[y]))
    return out


def edge_samples(a, b, c):
    x0, y0 = a
    x1, y1 = b
    if y1 < y0:
        x0, y0, x1, y1 = x1, y1, x0, y0
    dy = y1 - y0
    out = {}
    if dy == 0:
        out[y0] = (min(x0, x1), max(x0, x1))
        return out
    dx = abs(x1 - x0)
    sx = 1 if x1 >= x0 else -1
    err = 0
    x, y = x0, y0
    while True:
        out[y] = (x, x)
        if y == y1:
            break
        err += dx
        c['err_add'] += 1
        while err >= dy:
            err -= dy
            x += sx
            c['xstep'] += 1
        y += 1
    return out


def direct_spans(poly, c):
    # Exact current edge inclusion, but combine active edges directly without
    # clearing/writing/reading 192-byte left/right tables.
    rows = {}
    for i in range(len(poly)):
        es = edge_samples(poly[i], poly[(i + 1) % len(poly)], c)
        for y, (lo, hi) in es.items():
            c['boundary'] += 1
            if y in rows:
                a, b = rows[y]
                rows[y] = min(a, lo), max(b, hi)
            else:
                rows[y] = lo, hi
    out = []
    for y in sorted(rows):
        left, right = rows[y]
        if 0 <= y < H and left <= right:
            out.append((y, max(0, left), min(W - 1, right)))
            c['dda_scan'] += 1
    return out


def render(spans, fb, postdraw, c):
    for y, left, right in spans:
        b0, b1 = left >> 3, right >> 3
        for byte_x in range(b0, b1 + 1):
            left_mask = 0xFF >> (left & 7) if byte_x == b0 else 0xFF
            right_mask = (0xFF << (7 - (right & 7))) & 0xFF if byte_x == b1 else 0xFF
            mask = left_mask & right_mask
            index = y * 32 + byte_x
            old = fb[index]
            new = old | mask
            c['bytes_tested'] += 1
            if postdraw and new == old:
                continue
            fb[index] = new
            c['stores'] += 1
            if new != old:
                c['changed'] += 1


def score(c, kind):
    # Approximate relative Z80 T-state model, not emulator timing.
    if kind == 'base':
        return (c['clear'] * 21 + c['boundary'] * 45 + c['err_add'] * 24 +
                c['xstep'] * 36 + c['table_read'] * 18 +
                c['bytes_tested'] * 30 + c['stores'] * 12)
    return (c['boundary'] * 24 + c['err_add'] * 24 + c['xstep'] * 36 +
            c['dda_scan'] * 18 + c['bytes_tested'] * 30 + c['stores'] * 12)


def blank_counts():
    return {k: 0 for k in ('clear', 'boundary', 'err_add', 'xstep', 'table_read',
                           'dda_scan', 'bytes_tested', 'stores', 'changed')}


def run(seed=1, count=5000):
    r = random.Random(seed)
    values = {k: [] for k in ('baseline', 'direct', 'direct_post')}
    exact_equal = 0

    for _ in range(count):
        poly = [border_point(r) for _ in range(3)]
        cx = sum(x for x, _ in poly) / 3
        cy = sum(y for _, y in poly) / 3
        poly.sort(key=lambda p: math.atan2(p[1] - cy, p[0] - cx))

        c1, c2, c3 = blank_counts(), blank_counts(), blank_counts()
        baseline = baseline_spans(poly, c1)
        direct = direct_spans(poly, c2)

        f1, f2, f3 = bytearray(6144), bytearray(6144), bytearray(6144)
        render(baseline, f1, False, c1)
        render(direct, f2, False, c2)
        render(direct, f3, False, c3)
        render(direct, f3, True, c3)

        exact_equal += f1 == f2
        values['baseline'].append(score(c1, 'base'))
        values['direct'].append(score(c2, 'direct'))
        values['direct_post'].append(score(c3, 'direct'))

    result = {'triangles': count, 'exact_equal': exact_equal, 'modes': {}}
    for name, samples in values.items():
        result['modes'][name] = {
            'mean_modeled_t': statistics.mean(samples),
            'median_modeled_t': statistics.median(samples),
            'p95_modeled_t': statistics.quantiles(samples, n=20)[18],
        }
    result['speedup_direct'] = (result['modes']['baseline']['mean_modeled_t'] /
                                result['modes']['direct']['mean_modeled_t'])
    result['speedup_repeated_with_postdraw'] = (
        2 * result['modes']['direct']['mean_modeled_t'] /
        result['modes']['direct_post']['mean_modeled_t'])
    return result


if __name__ == '__main__':
    print(json.dumps(run(), indent=2))
