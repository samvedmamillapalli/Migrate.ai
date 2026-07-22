"""Bedrock call trace capture for durable explainability (Phase 11)."""

from __future__ import annotations

import time
from typing import Any

from app.prediction.bedrock_client import BedrockClient


def _usage_from_client(client: BedrockClient) -> tuple[int | None, int | None]:
    usage = getattr(client, "last_usage", None)
    if not isinstance(usage, dict):
        return None, None
    inp = usage.get("inputTokens")
    out = usage.get("outputTokens")
    try:
        return (
            int(inp) if inp is not None else None,
            int(out) if out is not None else None,
        )
    except (TypeError, ValueError):
        return None, None


def timed_generate(
    client: BedrockClient,
    *,
    system_prompt: str,
    user_prompt: str,
    model_id: str,
) -> tuple[str, float, int | None, int | None]:
    """Invoke Bedrock and return (text, latency_ms, input_tokens, output_tokens)."""
    started = time.perf_counter()
    text = client.generate_json(
        system_prompt=system_prompt,
        user_prompt=user_prompt,
        model_id=model_id,
    )
    latency_ms = round((time.perf_counter() - started) * 1000.0, 2)
    inp, out = _usage_from_client(client)
    return text, latency_ms, inp, out


def build_trace(
    *,
    kind: str,
    model_id: str,
    prompt_template_version: str,
    system_prompt: str,
    user_prompt: str,
    attempts: list[dict[str, Any]],
    repair_retried: bool,
    final_parsed: dict[str, Any] | None,
) -> dict[str, Any]:
    total = sum(
        float(a.get("latency_ms") or 0.0) for a in attempts if a.get("latency_ms") is not None
    )
    return {
        "kind": kind,
        "model_id": model_id,
        "prompt_template_version": prompt_template_version,
        "system_prompt": system_prompt,
        "user_prompt": user_prompt,
        "attempts": attempts,
        "repair_retried": repair_retried,
        "final_parsed": final_parsed,
        "latency_ms_total": round(total, 2) if attempts else None,
    }
