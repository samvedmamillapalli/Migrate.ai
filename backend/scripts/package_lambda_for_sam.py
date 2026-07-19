#!/usr/bin/env python3
"""Cross-platform SAM Makefile helper: copy app/ + install Lambda deps into ARTIFACTS_DIR."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path


def main() -> int:
    artifacts = Path(os.environ.get("ARTIFACTS_DIR") or (sys.argv[1] if len(sys.argv) > 1 else "")).resolve()
    if not artifacts.as_posix() or artifacts.as_posix() in {".", ""}:
        print("ARTIFACTS_DIR is required", file=sys.stderr)
        return 2

    backend = Path(__file__).resolve().parents[1]
    app_src = backend / "app"
    req = backend / "requirements-lambda.txt"
    if not app_src.is_dir():
        print(f"missing {app_src}", file=sys.stderr)
        return 2
    if not req.is_file():
        print(f"missing {req}", file=sys.stderr)
        return 2

    artifacts.mkdir(parents=True, exist_ok=True)
    for child in artifacts.iterdir():
        if child.is_dir():
            shutil.rmtree(child, ignore_errors=True)
        else:
            child.unlink(missing_ok=True)

    shutil.copytree(app_src, artifacts / "app")
    subprocess.check_call(
        [
            sys.executable,
            "-m",
            "pip",
            "install",
            "-r",
            str(req),
            "-t",
            str(artifacts),
            "--quiet",
            "--disable-pip-version-check",
        ]
    )
    for cache in artifacts.rglob("__pycache__"):
        shutil.rmtree(cache, ignore_errors=True)
    print(f"packed -> {artifacts}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
