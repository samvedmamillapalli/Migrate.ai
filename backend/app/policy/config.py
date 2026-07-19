"""Load and validate the committed policy YAML file."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

import yaml

from app.core.exceptions import AppError
from app.policy.models import PolicyFile

POLICY_FILE_PATH = Path(__file__).resolve().parent / "policy.yaml"


class PolicyConfigError(AppError):
    """Raised when the policy YAML is missing or malformed."""


def load_policy_file(path: Path | None = None) -> PolicyFile:
    """Load policy YAML and validate strictly. Fail loud on errors."""
    policy_path = path or POLICY_FILE_PATH
    if not policy_path.is_file():
        raise PolicyConfigError(f"Policy file not found: {policy_path}")

    try:
        raw = yaml.safe_load(policy_path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise PolicyConfigError(f"Policy YAML is not valid YAML: {exc}") from exc

    if not isinstance(raw, dict):
        raise PolicyConfigError("Policy YAML must be a mapping at the top level")

    try:
        return PolicyFile.model_validate(raw)
    except Exception as exc:
        raise PolicyConfigError(f"Policy YAML failed schema validation: {exc}") from exc


@lru_cache
def get_policy_file() -> PolicyFile:
    return load_policy_file()


def clear_policy_cache() -> None:
    get_policy_file.cache_clear()
