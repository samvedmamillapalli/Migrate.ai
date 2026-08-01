from pathlib import Path

SURPRISE_LESSONS_PROMPT_VERSION = "surprise_lessons_v1"

_PROMPTS_DIR = Path(__file__).resolve().parent


def load_prompt(name: str) -> str:
    path = _PROMPTS_DIR / name
    return path.read_text(encoding="utf-8")
