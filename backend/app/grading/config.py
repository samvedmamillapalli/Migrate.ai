"""Load and validate the committed grading YAML file."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

import yaml

from app.core.exceptions import AppError
from app.grading.models import GradingFile

GRADING_FILE_PATH = Path(__file__).resolve().parent / "grading.yaml"


class GradingConfigError(AppError):
    """Raised when the grading YAML is missing or malformed."""


def load_grading_file(path: Path | None = None) -> GradingFile:
    """Load grading YAML and validate strictly. Fail loud on errors."""
    grading_path = path or GRADING_FILE_PATH
    if not grading_path.is_file():
        raise GradingConfigError(f"Grading file not found: {grading_path}")

    try:
        raw = yaml.safe_load(grading_path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise GradingConfigError(f"Grading YAML is not valid YAML: {exc}") from exc

    if not isinstance(raw, dict):
        raise GradingConfigError("Grading YAML must be a mapping at the top level")

    try:
        return GradingFile.model_validate(raw)
    except Exception as exc:
        raise GradingConfigError(
            f"Grading YAML failed schema validation: {exc}"
        ) from exc


@lru_cache
def get_grading_file() -> GradingFile:
    return load_grading_file()


def clear_grading_cache() -> None:
    get_grading_file.cache_clear()
