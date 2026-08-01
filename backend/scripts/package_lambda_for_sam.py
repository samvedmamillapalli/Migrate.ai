#!/usr/bin/env python3
"""Cross-platform SAM Makefile helper: copy app/ + install Lambda deps into ARTIFACTS_DIR.

Always installs Linux x86_64 wheels (Lambda runtime), even when packaging on
Windows. Native wheels like pydantic_core / psycopg must match Amazon Linux.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

# Match infra/sam/template.yaml Runtime + Architectures.
_LAMBDA_PYTHON = "3.12"
_LAMBDA_PLATFORM = "manylinux2014_x86_64"


def _pip_install_linux(req: Path, artifacts: Path) -> None:
    """Install deps as Amazon Linux x86_64 / Python 3.12 wheels into artifacts."""
    base = [
        sys.executable,
        "-m",
        "pip",
        "install",
        "-r",
        str(req),
        "-t",
        str(artifacts),
        "--upgrade",
        "--quiet",
        "--disable-pip-version-check",
        "--platform",
        _LAMBDA_PLATFORM,
        "--implementation",
        "cp",
        "--python-version",
        _LAMBDA_PYTHON,
        "--only-binary=:all:",
    ]
    try:
        subprocess.check_call(base)
        return
    except subprocess.CalledProcessError:
        print(
            "WARN: full --only-binary Linux install failed; "
            "retrying binary packages then pure-Python packages",
            file=sys.stderr,
        )

    binary_pkgs = [
        "pydantic>=2.0",
        "pydantic-settings>=2.6.0",
        "psycopg[binary]>=3.2.0",
        "sqlalchemy[asyncio]>=2.0.36",
        "greenlet",
    ]
    subprocess.check_call(
        [
            sys.executable,
            "-m",
            "pip",
            "install",
            *binary_pkgs,
            "-t",
            str(artifacts),
            "--upgrade",
            "--quiet",
            "--disable-pip-version-check",
            "--platform",
            _LAMBDA_PLATFORM,
            "--implementation",
            "cp",
            "--python-version",
            _LAMBDA_PYTHON,
            "--only-binary=:all:",
        ]
    )
    pure_pkgs = [
        "boto3>=1.35.0",
        "sqlalchemy-cockroachdb>=2.0.2",
        "httpx>=0.28.0",
        "sqlglot>=26.0.0",
        "PyYAML>=6.0.0",
    ]
    subprocess.check_call(
        [
            sys.executable,
            "-m",
            "pip",
            "install",
            *pure_pkgs,
            "-t",
            str(artifacts),
            "--upgrade",
            "--quiet",
            "--disable-pip-version-check",
        ]
    )


def main() -> int:
    artifacts = Path(
        os.environ.get("ARTIFACTS_DIR") or (sys.argv[1] if len(sys.argv) > 1 else "")
    ).resolve()
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

    # Bundle Cockroach CA when available so Lambda verify-full URLs work.
    # Prefer the repo-bundled public CA so packaging works without a host install.
    repo_root = Path(__file__).resolve().parents[2]
    ca_candidates = [
        repo_root / "certs" / "cockroach-cloud-ca.crt",
        repo_root / "certs" / "root.crt",
    ]
    appdata = os.environ.get("APPDATA")
    if appdata:
        ca_candidates.append(Path(appdata) / "postgresql" / "root.crt")
    ca_candidates.append(Path.home() / ".postgresql" / "root.crt")
    for ca in ca_candidates:
        if ca.is_file():
            certs_dir = artifacts / "certs"
            certs_dir.mkdir(parents=True, exist_ok=True)
            shutil.copy2(ca, certs_dir / "root.crt")
            print(f"Bundled Cockroach CA -> {certs_dir / 'root.crt'}", flush=True)
            break

    print(
        f"Installing Lambda deps for {_LAMBDA_PLATFORM} / cp{_LAMBDA_PYTHON} ...",
        flush=True,
    )
    _pip_install_linux(req, artifacts)
    for cache in artifacts.rglob("__pycache__"):
        shutil.rmtree(cache, ignore_errors=True)
    pyds = list(artifacts.rglob("*.pyd"))
    win_native = [p for p in pyds if "pydantic" in p.name.lower() or "psycopg" in str(p).lower()]
    if win_native:
        print(
            "ERROR: Windows native binary ended up in the Lambda package: "
            f"{win_native[0]}. Refusing to ship a broken Linux function.",
            file=sys.stderr,
        )
        return 3
    so_files = [
        p
        for p in artifacts.rglob("*.so")
        if "pydantic_core" in p.name or p.parent.name == "pydantic_core"
    ]
    if not so_files:
        # Also accept _pydantic_core.*.so naming
        so_files = list(artifacts.glob("**/pydantic_core/*.so")) + list(
            artifacts.glob("**/_pydantic_core*.so")
        )
    if not so_files:
        print(
            "ERROR: pydantic_core Linux .so missing from package — "
            "Lambda would fail with ImportModuleError.",
            file=sys.stderr,
        )
        return 3
    print(f"packed -> {artifacts} (pydantic_core={so_files[0].name})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
