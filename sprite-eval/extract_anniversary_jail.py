#!/usr/bin/env python3
"""Extract the unencrypted Jail resources from the official demo Pak01.pak.

The generated JavaScript is build input only and remains uncommitted.  It uses
raw base64 so the same headless another_js VM can audit the actual Buddy
composites without redistributing the source pack.
"""
from __future__ import annotations

import argparse
import base64
import struct
from pathlib import Path


RESOURCE_NAMES = {17: "11", 29: "1d", 30: "1e", 31: "1f"}


def extract(pak_path: Path) -> dict[str, bytes]:
    found: dict[str, bytes] = {}
    with pak_path.open("rb") as stream:
        if stream.read(4) != b"PACK":
            raise RuntimeError(f"{pak_path} is not a 15th Anniversary PACK file")
        table_offset = struct.unpack("<I", stream.read(4))[0]
        index = 0
        while True:
            stream.seek(table_offset + 64 * index)
            header = stream.read(64)
            if len(header) != 64:
                break
            index += 1
            raw_name = header[:56].split(b"\0", 1)[0]
            if not raw_name:
                continue
            name = raw_name.decode("latin1")
            for resource, suffix in RESOURCE_NAMES.items():
                if name != f"dlx/file{resource:03d}.dat":
                    continue
                offset, size = struct.unpack("<II", header[56:64])
                stream.seek(offset)
                payload = stream.read(size)
                if len(payload) != size:
                    raise RuntimeError(f"truncated {name}: expected {size}, got {len(payload)}")
                if payload.startswith(b"TooDC"):
                    raise RuntimeError(f"{name} is encrypted in this pack")
                found[suffix] = payload
    missing = sorted(set(RESOURCE_NAMES.values()) - found.keys())
    if missing:
        raise RuntimeError(f"Jail resource(s) not found: {', '.join(missing)}")
    return found


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("pak", type=Path, help="official Anniversary demo Data/Pak01.pak")
    parser.add_argument("out", type=Path, help="generated raw-resource JavaScript")
    args = parser.parse_args()
    resources = extract(args.pak)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    lines = []
    for suffix in ("11", "1d", "1e", "1f"):
        payload = resources[suffix]
        encoded = base64.b64encode(payload).decode("ascii")
        lines.extend(
            (
                f'const data{suffix} = "{encoded}";',
                f"const size{suffix} = {len(payload)};",
            )
        )
    lines.extend(("const bitmaps = {};", "const strings_en = {};", "const strings_fr = {};", ""))
    args.out.write_text("\n".join(lines), encoding="utf-8")
    print(
        f"wrote {args.out} with "
        + ", ".join(f"data{suffix}={len(resources[suffix])}" for suffix in ("11", "1d", "1e", "1f"))
    )


if __name__ == "__main__":
    main()
