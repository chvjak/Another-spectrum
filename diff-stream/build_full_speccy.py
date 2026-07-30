#!/usr/bin/env python3
"""Entry point for the AY-integrated diff-stream builder.

The implementation is stored in line-preserving source fragments so GitHub's
connector can preserve the recovered/generated source without binary transport.
They are concatenated before compilation; tracebacks use a synthetic
`build_full_speccy_impl.py` filename.
"""
from pathlib import Path

_parts = Path(__file__).resolve().parent / "build_full_speccy_parts"
_source = "".join((_parts / f"{index:02}.pyfrag").read_text(encoding="utf-8") for index in range(5))
exec(
    compile(_source, str(Path(__file__).with_name("build_full_speccy_impl.py")), "exec"),
    globals(),
    globals(),
)
