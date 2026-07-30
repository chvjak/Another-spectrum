#!/usr/bin/env python3
"""Build the VM port with the ST-style full-byte span writer.

The canonical renderer_full.asm is restored even when the underlying build
fails, keeping the source checkout clean.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

from st_renderer_patch import patch_renderer

ROOT = Path(__file__).resolve().parent
RENDERER = ROOT / "renderer_full.asm"
BUILD = ROOT / "build-full"
GENERATED = BUILD / "renderer_full_st.asm"


def main() -> int:
    BUILD.mkdir(parents=True, exist_ok=True)
    original = RENDERER.read_text(encoding="utf-8")
    generated = patch_renderer(original)
    GENERATED.write_text(generated, encoding="utf-8")

    # build_full_vm_port.py currently names renderer_full.asm explicitly. Swap
    # the generated source in atomically and always restore the tracked file.
    backup = RENDERER.with_suffix(".asm.st-backup")
    if backup.exists():
        raise RuntimeError(f"stale backup exists: {backup}")
    shutil.copy2(RENDERER, backup)
    try:
        RENDERER.write_text(generated, encoding="utf-8")
        command = [sys.executable, str(ROOT / "build_full_vm_port.py"), *sys.argv[1:]]
        completed = subprocess.run(command, cwd=ROOT)
        if completed.returncode != 0:
            return completed.returncode
        if (BUILD / "renderer-code.bin").exists():
            shutil.copy2(BUILD / "renderer-code.bin", BUILD / "renderer-code-st.bin")
        if (BUILD / "manifest.json").exists():
            shutil.copy2(BUILD / "manifest.json", BUILD / "manifest-st.json")
        return 0
    finally:
        os.replace(backup, RENDERER)


if __name__ == "__main__":
    raise SystemExit(main())
