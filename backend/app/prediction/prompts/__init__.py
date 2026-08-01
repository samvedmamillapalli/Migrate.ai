"""Versioned prompt template loading."""

from __future__ import annotations

from pathlib import Path

PROMPTS_DIR = Path(__file__).resolve().parent

PREDICTION_PROMPT_VERSION = "prediction_v3"
RECOMMENDATION_PROMPT_VERSION = "recommendation_v3"


def load_prompt(version: str) -> str:
    path = PROMPTS_DIR / f"{version}.txt"
    if not path.is_file():
        raise FileNotFoundError(f"Prompt template not found: {path}")
    return path.read_text(encoding="utf-8").strip()
