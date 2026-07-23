"""In-process pipeline progress for live UI polling during long Bedrock calls.

Single-process uvicorn is enough for local/dev. Cleared when a pipeline finishes.
"""

from __future__ import annotations

import threading
import time
from typing import Any

_lock = threading.Lock()
_PROGRESS: dict[str, dict[str, Any]] = {}


def set_progress(
    run_id: str | Any,
    *,
    stage: str,
    message: str,
    percent: int,
    detail: str | None = None,
) -> None:
    key = str(run_id)
    payload = {
        "run_id": key,
        "stage": stage,
        "message": message,
        "percent": max(0, min(100, int(percent))),
        "detail": detail,
        "updated_at": time.time(),
    }
    with _lock:
        prev = _PROGRESS.get(key) or {}
        history = list(prev.get("history") or [])
        if not history or history[-1].get("stage") != stage:
            history.append(
                {
                    "stage": stage,
                    "message": message,
                    "percent": payload["percent"],
                    "at": payload["updated_at"],
                }
            )
            # Keep last ~20 stage entries for the UI console.
            history = history[-20:]
        payload["history"] = history
        _PROGRESS[key] = payload


def get_progress(run_id: str | Any) -> dict[str, Any] | None:
    with _lock:
        data = _PROGRESS.get(str(run_id))
        return dict(data) if data else None


def clear_progress(run_id: str | Any) -> None:
    with _lock:
        _PROGRESS.pop(str(run_id), None)


__all__ = ["set_progress", "get_progress", "clear_progress"]
