"""Real CockroachDB Managed MCP Server client.

See docs/COCKROACHDB_MCP_INTEGRATION_PLAN.md for the design and the Phase A
spike that verified this against a real cluster (this app's existing
CCLOUD_API_SECRET service-account credential authenticates to
https://cockroachlabs.cloud/mcp with an `mcp-cluster-id` header, and every
tool call below is a real tool — `list_databases`, `get_table_schema`,
`select_query`, etc. — returning real data, not a simulation).

Read-only by construction, not just by convention: `ShadowMcpSession.tool_defs()`
filters out the server's write tools (`create_database`, `create_table`,
`insert_rows`) before any tool list is ever built into a model's toolConfig,
and `call_tool` refuses to call them even if asked. This mirrors the app's
existing posture toward the shadow cluster elsewhere (best-effort, capped,
never allowed to fail the migration it's investigating).
"""

from __future__ import annotations

import contextlib
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any

from app.core.logging import get_logger

logger = get_logger(__name__)

_WRITE_TOOL_NAMES = frozenset({"create_database", "create_table", "insert_rows"})


class McpToolBudgetExceeded(Exception):
    """Raised when a session's call_tool budget is exhausted."""


@dataclass
class McpToolDef:
    name: str
    description: str
    input_schema: dict[str, Any]


@dataclass
class McpToolCall:
    """One real tool call and its real result — the receipts a ModelTrace
    needs so a claim in the investigation's verdict can be checked against
    what the tool actually returned, not just the model's prose."""

    name: str
    arguments: dict[str, Any]
    result_text: str
    is_error: bool


@dataclass
class ShadowMcpSession:
    """One MCP session scoped to one real CockroachDB Cloud cluster."""

    _session: Any
    max_calls: int = 8
    calls_made: int = field(default=0, init=False)
    call_log: list[McpToolCall] = field(default_factory=list, init=False)

    async def tool_defs(self) -> list[McpToolDef]:
        result = await self._session.list_tools()
        return [
            McpToolDef(
                name=t.name,
                description=t.description or "",
                input_schema=t.input_schema or {"type": "object", "properties": {}},
            )
            for t in result.tools
            if t.name not in _WRITE_TOOL_NAMES
        ]

    async def call_tool(self, name: str, arguments: dict[str, Any]) -> McpToolCall:
        if name in _WRITE_TOOL_NAMES:
            call = McpToolCall(
                name=name,
                arguments=arguments,
                result_text=(
                    f"Refused: '{name}' is a write tool and this investigation "
                    "session is read-only."
                ),
                is_error=True,
            )
            self.call_log.append(call)
            return call
        if self.calls_made >= self.max_calls:
            raise McpToolBudgetExceeded(
                f"MCP tool-call budget ({self.max_calls}) exhausted"
            )
        self.calls_made += 1
        try:
            result = await self._session.call_tool(name, arguments)
            text = "\n".join(
                part.text for part in result.content if hasattr(part, "text")
            )
            call = McpToolCall(
                name=name,
                arguments=arguments,
                result_text=text,
                is_error=bool(getattr(result, "isError", False)),
            )
        except Exception as exc:  # noqa: BLE001 - a failed call is a finding, not a crash
            call = McpToolCall(
                name=name,
                arguments=arguments,
                result_text=f"{type(exc).__name__}: {exc}",
                is_error=True,
            )
        self.call_log.append(call)
        return call


@contextlib.asynccontextmanager
async def open_shadow_mcp_session(
    *,
    cluster_id: str,
    api_secret: str,
    base_url: str,
    max_calls: int = 8,
) -> AsyncIterator[ShadowMcpSession | None]:
    """Yields a ready session, or None if MCP is unavailable — never raises.

    This is enrichment on top of an already-measured migration, never a
    dependency of it. Any connection failure (network, auth, the `mcp`
    package missing) degrades to "investigation skipped," logged once, not a
    failed migration. Only the connection/handshake is best-effort like
    this — once a session is successfully yielded, exceptions raised while
    using it propagate normally (the caller decides how to handle a failure
    mid-investigation, e.g. as an incomplete-but-partial trace).
    """
    try:
        import mcp.client.streamable_http as sh
        from mcp import ClientSession
    except ImportError:
        logger.warning("mcp package not installed; skipping MCP investigation")
        yield None
        return

    headers = {
        "Authorization": f"Bearer {api_secret}",
        "mcp-cluster-id": cluster_id,
    }

    async with contextlib.AsyncExitStack() as stack:
        try:
            http_client = await stack.enter_async_context(
                sh.create_mcp_http_client(headers=headers)
            )
            read, write = await stack.enter_async_context(
                sh.streamable_http_client(base_url, http_client=http_client)
            )
            raw_session = await stack.enter_async_context(ClientSession(read, write))
            await raw_session.initialize()
        except Exception as exc:  # noqa: BLE001 - best-effort, never blocks the migration
            logger.warning(
                "MCP session unavailable; investigation will be skipped",
                extra={"cluster_id": cluster_id, "error": f"{type(exc).__name__}: {exc}"},
            )
            yield None
            return

        yield ShadowMcpSession(_session=raw_session, max_calls=max_calls)
