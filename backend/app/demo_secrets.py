"""Where the local judge/demo credential files live.

These are gitignored, developer-machine-only files used by the demo path and the
judge walkthrough scripts. They moved from the repo root into ``.local_secrets/``
so credential-shaped files aren't sitting loose at the top of a public repo
(docs/HACKATHON_INTEGRATION_AUDIT.md §4.1).

Resolution order, so an existing checkout keeps working without manual steps:

1. ``.local_secrets/<name>``  — the current location
2. ``<repo root>/<name>``     — the legacy location, still read if present

Writers should always use :func:`demo_secret_write_path`, which targets the new
location and creates the directory.
"""

from __future__ import annotations

from pathlib import Path

# backend/app/demo_secrets.py → parents[2] = repo root
REPO_ROOT = Path(__file__).resolve().parents[2]
LOCAL_SECRETS_DIR = REPO_ROOT / ".local_secrets"

JUDGE_RO_DATABASE_URL_FILE = "judge_ro_database_url"
JUDGE_RO_PASSWORD_FILE = "judge_ro_password"


def demo_secret_path(name: str) -> Path | None:
    """Return the first existing path for a demo secret, or None.

    ``name`` may be given with or without the legacy leading dot — both
    ``judge_ro_database_url`` and ``.judge_ro_database_url`` resolve the same.
    """
    bare = name.lstrip(".")
    candidates = (
        LOCAL_SECRETS_DIR / f".{bare}",
        LOCAL_SECRETS_DIR / bare,
        REPO_ROOT / f".{bare}",
    )
    for path in candidates:
        if path.is_file():
            return path
    return None


def read_demo_secret(name: str) -> str | None:
    """Read and strip a demo secret file, or None when it isn't present."""
    path = demo_secret_path(name)
    if path is None:
        return None
    value = path.read_text(encoding="utf-8").strip()
    return value or None


def demo_secret_write_path(name: str) -> Path:
    """Canonical write location (``.local_secrets/.<name>``); dir is created."""
    LOCAL_SECRETS_DIR.mkdir(parents=True, exist_ok=True)
    return LOCAL_SECRETS_DIR / f".{name.lstrip('.')}"
