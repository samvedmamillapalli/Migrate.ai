#!/usr/bin/env python3
"""Developer entrypoint - bootstrap + run API.

The operator UI is the Next.js app under ``frontend/oracle``
(``npm run dev`` -> http://localhost:3000). The legacy static ``/ui`` console
is retired.

Usage (from repo root):
  python scripts/dev.py setup    # venv + deps + migrations + readiness check
  python scripts/dev.py doctor   # verify .env / AWS / SFN without starting
  python scripts/dev.py          # start API (auto-setup if needed)
  python scripts/dev.py restart  # kill port, clear stale env, start fresh
  .\\dev.ps1 / ./dev.sh
  .\\restart.ps1 / ./restart.sh

Env:
  DEV_HOST   default 127.0.0.1
  DEV_PORT   default 8000
  DEV_RELOAD default 1 (set 0 to disable)
  DEV_SKIP_SETUP=1  skip auto-setup on serve
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
BACKEND_DIR = REPO_ROOT / "backend"
ENV_FILE = REPO_ROOT / ".env"
REQUIREMENTS = BACKEND_DIR / "requirements.txt"

# Minimum keys for full AWS + Cockroach + Bedrock + real Step Functions shadow.
REQUIRED_KEYS = (
    "DATABASE_URL",
    "AWS_DEFAULT_REGION",
    "MIGRATION_WORKFLOW_ARN",
    "RUN_ARTIFACTS_BUCKET",
    "BEDROCK_PREDICTION_MODEL_ID",
    "BEDROCK_EMBEDDING_MODEL_ID",
    "CCLOUD_API_SECRET",
    "SHADOW_PROVIDER",
)
# At least one AWS auth path must be present.
AWS_AUTH_KEYS = ("AWS_ACCESS_KEY_ID", "AWS_PROFILE")


def _env_bool(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None or raw.strip() == "":
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _venv_python() -> Path | None:
    if sys.platform == "win32":
        candidates = [
            BACKEND_DIR / ".venv" / "Scripts" / "python.exe",
            REPO_ROOT / ".venv" / "Scripts" / "python.exe",
        ]
    else:
        candidates = [
            BACKEND_DIR / ".venv" / "bin" / "python",
            REPO_ROOT / ".venv" / "bin" / "python",
        ]
    for path in candidates:
        if path.is_file():
            return path
    return None


def _resolve_python() -> str:
    found = _venv_python()
    return str(found) if found else sys.executable


def _run(cmd: list[str], *, cwd: Path | None = None) -> None:
    print(f"+ {' '.join(cmd)}")
    subprocess.check_call(cmd, cwd=str(cwd) if cwd else None)


def _parse_dotenv(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.is_file():
        return values
    for raw in path.read_text(encoding="utf-8-sig").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip().strip('"').strip("'")
    return values


def _bundled_ca_cert() -> Path | None:
    for name in ("cockroach-cloud-ca.crt", "root.crt"):
        path = REPO_ROOT / "certs" / name
        if path.is_file():
            return path
    return None


def _host_ca_cert_dest() -> Path:
    if sys.platform == "win32":
        appdata = os.environ.get("APPDATA")
        if not appdata:
            raise SystemExit("APPDATA is unset; cannot install Cockroach CA")
        return Path(appdata) / "postgresql" / "root.crt"
    return Path.home() / ".postgresql" / "root.crt"


def _ca_cert_path() -> Path | None:
    """Any usable CA: host libpq path, then repo-bundled public cert."""
    candidates: list[Path] = []
    if sys.platform == "win32":
        appdata = os.environ.get("APPDATA")
        if appdata:
            candidates.append(Path(appdata) / "postgresql" / "root.crt")
    candidates.append(Path.home() / ".postgresql" / "root.crt")
    bundled = _bundled_ca_cert()
    if bundled is not None:
        candidates.append(bundled)
    for path in candidates:
        if path.is_file():
            return path
    return None


def _ensure_ca_cert() -> Path | None:
    """Ensure a usable CA exists; install host copy from the repo bundle if needed."""
    host = _host_ca_cert_dest()
    if host.is_file():
        return host

    bundled = _bundled_ca_cert()
    if bundled is not None:
        host.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(bundled, host)
        print(f"Installed Cockroach CA -> {host}")
        return host

    return _ca_cert_path()


def _check_python_version() -> None:
    if sys.version_info < (3, 12):
        raise SystemExit(
            f"Python 3.12+ required (found {sys.version.split()[0]}). "
            "Install 3.12+ and re-run."
        )


def _ensure_venv() -> Path:
    existing = _venv_python()
    if existing is not None:
        print(f"venv ok: {existing}")
        return existing

    venv_dir = BACKEND_DIR / ".venv"
    print(f"Creating venv at {venv_dir} ...")
    _run([sys.executable, "-m", "venv", str(venv_dir)])
    py = _venv_python()
    if py is None:
        raise SystemExit("venv created but python not found inside it")
    return py


def _pip_install(py: Path) -> None:
    if not REQUIREMENTS.is_file():
        raise SystemExit(f"missing {REQUIREMENTS}")
    _run([str(py), "-m", "pip", "install", "--upgrade", "pip"])
    _run([str(py), "-m", "pip", "install", "-r", str(REQUIREMENTS)])


def _alembic_upgrade(py: Path) -> None:
    _run([str(py), "-m", "alembic", "upgrade", "head"], cwd=BACKEND_DIR)


def _print_env_gaps(env: dict[str, str]) -> list[str]:
    missing: list[str] = []
    for key in REQUIRED_KEYS:
        if not env.get(key):
            missing.append(key)
    has_auth = bool(env.get("AWS_ACCESS_KEY_ID") and env.get("AWS_SECRET_ACCESS_KEY"))
    has_profile = bool(env.get("AWS_PROFILE"))
    if not has_auth and not has_profile:
        missing.append("AWS_ACCESS_KEY_ID+AWS_SECRET_ACCESS_KEY (or AWS_PROFILE)")
    return missing


def cmd_doctor(_args: argparse.Namespace) -> int:
    """Readiness check for full AWS + Cockroach + Bedrock + SFN path."""
    print("Migration Oracle - doctor")
    ok = True

    if not ENV_FILE.is_file():
        print(f"FAIL  .env missing at {ENV_FILE}")
        print("      Ask a teammate for the shared filled .env (do not commit it).")
        return 1
    print(f"OK    .env present")

    env = _parse_dotenv(ENV_FILE)
    missing = _print_env_gaps(env)
    if missing:
        ok = False
        print(f"FAIL  missing keys: {', '.join(missing)}")
    else:
        print("OK    required keys set (DATABASE_URL, AWS, Bedrock, SFN, CCloud)")

    arn = bool(env.get("MIGRATION_WORKFLOW_ARN"))
    bucket = bool(env.get("RUN_ARTIFACTS_BUCKET"))
    if arn and bucket:
        print("OK    SFN ready (workflow ARN + artifacts bucket)")
    else:
        ok = False
        print("FAIL  SFN not ready - need MIGRATION_WORKFLOW_ARN + RUN_ARTIFACTS_BUCKET")
        print("      Shared stack is already deployed; copy outputs from a teammate .env")

    db_url = env.get("DATABASE_URL", "")
    if "sslmode=verify-full" in db_url or "sslmode=verify-ca" in db_url:
        ca = _ca_cert_path()
        if ca:
            print(f"OK    Cockroach CA cert: {ca}")
        else:
            ok = False
            print("FAIL  Cockroach CA cert not found")
            print("      Expected repo file certs/cockroach-cloud-ca.crt, or host path:")
            if sys.platform == "win32":
                print(r"        %APPDATA%\postgresql\root.crt")
            else:
                print("        ~/.postgresql/root.crt")
            print("      Re-pull the branch, or run: python scripts/dev.py setup")

    provider = (env.get("SHADOW_PROVIDER") or "").strip().lower()
    if provider and provider != "ccloud_api":
        print(f"WARN  SHADOW_PROVIDER={provider!r} (expected ccloud_api for real shadows)")

    py = _venv_python()
    if py:
        print(f"OK    venv python: {py}")
    else:
        print("WARN  no backend/.venv - run: python scripts/dev.py setup")

    print()
    if ok:
        print("RESULT: ready - run: python scripts/dev.py restart")
        print("         (or .\\restart.ps1 / ./restart.sh)")
        return 0
    print("RESULT: not ready - fix FAIL lines above, then re-run doctor")
    return 1


def cmd_setup(args: argparse.Namespace) -> int:
    """Create venv, install deps, migrate DB, then doctor."""
    print("Migration Oracle - setup")
    _check_python_version()

    if not ENV_FILE.is_file():
        example = REPO_ROOT / ".env.example"
        print(f"error: {ENV_FILE} not found.", file=sys.stderr)
        print(
            "Get the shared filled .env from a teammate and place it at the repo root.",
            file=sys.stderr,
        )
        if example.is_file():
            print(f"(Or copy {example.name} and fill the TEAMMATE MINIMUM section.)", file=sys.stderr)
        return 1

    env = _parse_dotenv(ENV_FILE)
    missing = _print_env_gaps(env)
    if missing and not args.allow_partial:
        print("error: .env is incomplete for the full cloud demo path:", file=sys.stderr)
        for key in missing:
            print(f"  - {key}", file=sys.stderr)
        print("Ask a teammate for the shared filled .env, or pass --allow-partial.", file=sys.stderr)
        return 1

    ca = _ensure_ca_cert()
    if ca is None and (
        "sslmode=verify-full" in env.get("DATABASE_URL", "")
        or "sslmode=verify-ca" in env.get("DATABASE_URL", "")
    ):
        print(
            "error: Cockroach CA missing. Expected certs/cockroach-cloud-ca.crt in the repo.",
            file=sys.stderr,
        )
        return 1

    py = _ensure_venv()
    if not args.skip_install:
        _pip_install(py)
    if not args.skip_migrate:
        _alembic_upgrade(py)

    print("Ensuring open-source migration corpus ...")
    _run([str(py), str(BACKEND_DIR / "scripts" / "seed_open_source_corpus.py")])

    print()
    return cmd_doctor(args)


def cmd_serve(args: argparse.Namespace) -> int:
    host = args.host or os.environ.get("DEV_HOST", "127.0.0.1")
    port = int(args.port or os.environ.get("DEV_PORT", "8000"))
    reload = args.reload if args.reload is not None else _env_bool("DEV_RELOAD", True)

    if not BACKEND_DIR.is_dir():
        print(f"error: backend directory not found: {BACKEND_DIR}", file=sys.stderr)
        return 1

    if _venv_python() is None and not _env_bool("DEV_SKIP_SETUP", False):
        print("No backend/.venv found - running setup first...")
        print()
        code = cmd_setup(argparse.Namespace(allow_partial=False, skip_install=False, skip_migrate=False))
        if code != 0:
            return code
        print()

    py = _resolve_python()
    docs = f"http://{host}:{port}/docs"
    health = f"http://{host}:{port}/health"
    print("Migration Oracle - local development")
    print(f"  Interpreter : {py}")
    print(f"  API         : uvicorn (host={host} port={port} reload={reload})")
    print(f"  Health      : {health}")
    print(f"  OpenAPI     : {docs}")
    print("  Operator UI : cd frontend/oracle && npm run dev  ->  http://localhost:3000")
    print("  Tip: /health integrations.sfn_ready should be true for real AWS shadows.")
    if sys.platform == "win32":
        print("  Windows tip: keep --reload (default) so psycopg gets a Selector loop.")
    print()
    # #region agent log
    try:
        import json as _json
        import time as _time

        _log = REPO_ROOT / "debug-a64fa9.log"
        with _log.open("a", encoding="utf-8") as _f:
            _f.write(
                _json.dumps(
                    {
                        "sessionId": "a64fa9",
                        "runId": "post-fix",
                        "hypothesisId": "F",
                        "location": "scripts/dev.py:cmd_serve",
                        "message": "serve_starting_after_banner",
                        "data": {"host": host, "port": port, "reload": reload},
                        "timestamp": int(_time.time() * 1000),
                    }
                )
                + "\n"
            )
    except Exception:
        pass
    # #endregion

    cmd = [
        py,
        "-m",
        "uvicorn",
        "app.main:app",
        "--host",
        host,
        "--port",
        str(port),
        "--app-dir",
        str(BACKEND_DIR),
    ]
    if reload:
        cmd.append("--reload")

    return subprocess.call(cmd, cwd=str(BACKEND_DIR))


def _stop_port(port: int) -> None:
    """Best-effort kill of whatever is listening on ``port`` (fresh restart)."""
    if sys.platform == "win32":
        # PowerShell: find PIDs bound to the port and stop them.
        ps = (
            f"$conns = Get-NetTCPConnection -LocalPort {port} -State Listen "
            f"-ErrorAction SilentlyContinue; "
            f"if ($conns) {{ $conns | Select-Object -ExpandProperty OwningProcess "
            f"-Unique | ForEach-Object {{ Stop-Process -Id $_ -Force "
            f"-ErrorAction SilentlyContinue }} }}"
        )
        subprocess.run(
            ["powershell", "-NoProfile", "-Command", ps],
            check=False,
            capture_output=True,
        )
        return

    # macOS / Linux
    try:
        out = subprocess.check_output(["lsof", "-ti", f"tcp:{port}"], text=True)
    except (subprocess.CalledProcessError, FileNotFoundError):
        return
    for pid in {p.strip() for p in out.splitlines() if p.strip()}:
        subprocess.run(["kill", "-9", pid], check=False)


def _clear_stale_dotenv_overrides() -> None:
    """Drop process-env copies of .env keys so repo-root .env is authoritative."""
    keys = [
        "DATABASE_URL",
        "CCLOUD_API_SECRET",
        "CCLOUD_API_KEY",
        "CCLOUD_API_KEY_SECRET_ARN",
        "MIGRATION_WORKFLOW_ARN",
        "RUN_ARTIFACTS_BUCKET",
        "AWS_ACCESS_KEY_ID",
        "AWS_SECRET_ACCESS_KEY",
        "AWS_SESSION_TOKEN",
        "AWS_PROFILE",
        "AWS_DEFAULT_REGION",
        "BEDROCK_PREDICTION_MODEL_ID",
        "BEDROCK_EMBEDDING_MODEL_ID",
        "SHADOW_PROVIDER",
    ]
    for key in keys:
        os.environ.pop(key, None)


def cmd_restart(args: argparse.Namespace) -> int:
    """Stop the local API on DEV_PORT, clear stale env, then start fresh."""
    host = args.host or os.environ.get("DEV_HOST", "127.0.0.1")
    port = int(args.port or os.environ.get("DEV_PORT", "8000"))
    print(f"Migration Oracle - fresh restart (port {port})")
    print(f"  Stopping anything listening on {host}:{port} ...")
    _stop_port(port)
    _clear_stale_dotenv_overrides()
    print("  Cleared stale process env overrides (will reload repo .env)")
    print()
    # Reuse serve defaults
    serve_args = argparse.Namespace(
        host=args.host,
        port=args.port,
        reload=args.reload,
    )
    return cmd_serve(serve_args)


def cmd_deploy(_args: argparse.Namespace) -> int:
    print(
        "Teammates do NOT need to deploy - the shared stack `migration-oracle`\n"
        "is already up. Put MIGRATION_WORKFLOW_ARN + RUN_ARTIFACTS_BUCKET in .env.\n"
        "\n"
        "Only re-deploy when Lambda/ASL code changes (once per account):\n"
        "  cd infra/sam\n"
        "  .\\build.ps1   # Windows\n"
        "  .\\deploy.ps1\n"
        "See docs/DEPLOYMENT.md.",
        file=sys.stderr,
    )
    return 2


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="dev",
        description="Bootstrap and run Migration Oracle locally (API; Next.js UI separate).",
    )
    sub = parser.add_subparsers(dest="command")

    setup = sub.add_parser("setup", help="venv + deps + alembic + readiness check")
    setup.add_argument(
        "--allow-partial",
        action="store_true",
        help="Continue even if some .env keys are missing",
    )
    setup.add_argument("--skip-install", action="store_true")
    setup.add_argument("--skip-migrate", action="store_true")
    setup.set_defaults(func=cmd_setup)

    doctor = sub.add_parser("doctor", help="Check .env / CA / SFN readiness")
    doctor.set_defaults(func=cmd_doctor)

    serve = sub.add_parser("serve", help="Start local API + UI (default)")
    serve.add_argument("--host", default=None, help="Bind host (env DEV_HOST)")
    serve.add_argument("--port", type=int, default=None, help="Bind port (env DEV_PORT)")
    serve.add_argument(
        "--reload",
        dest="reload",
        action="store_true",
        default=None,
        help="Enable auto-reload",
    )
    serve.add_argument(
        "--no-reload",
        dest="reload",
        action="store_false",
        help="Disable auto-reload",
    )
    serve.set_defaults(func=cmd_serve)

    restart = sub.add_parser(
        "restart",
        help="Kill port listener, clear stale env, start API + UI fresh",
    )
    restart.add_argument("--host", default=None, help="Bind host (env DEV_HOST)")
    restart.add_argument("--port", type=int, default=None, help="Bind port (env DEV_PORT)")
    restart.add_argument(
        "--reload",
        dest="reload",
        action="store_true",
        default=None,
        help="Enable auto-reload",
    )
    restart.add_argument(
        "--no-reload",
        dest="reload",
        action="store_false",
        help="Disable auto-reload",
    )
    restart.set_defaults(func=cmd_restart)

    deploy = sub.add_parser(
        "deploy",
        help="Explain shared-stack deploy (not needed for normal teammates)",
    )
    deploy.set_defaults(func=cmd_deploy)
    return parser


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    parser = build_parser()
    known = {"serve", "setup", "doctor", "restart", "deploy", "-h", "--help"}
    if not argv or argv[0] not in known:
        argv = ["serve", *argv]
    args = parser.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
