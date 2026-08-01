"""Windows-safe uvicorn entrypoint (SelectorEventLoop for psycopg).

uvicorn's own loop factory (uvicorn.loops.asyncio.asyncio_loop_factory)
unconditionally returns asyncio.ProactorEventLoop on win32, and
Server.run() passes that to asyncio.run() as an explicit loop_factory —
which overrides any asyncio event loop *policy* set beforehand. Setting
WindowsSelectorEventLoopPolicy before importing uvicorn (the old approach)
has no effect under this uvicorn version because of that. Bypassing
Server.run() and driving asyncio.run() with our own loop_factory is what
actually makes psycopg's async driver work on Windows.
"""

from __future__ import annotations

import asyncio
import sys

import uvicorn


def _selector_event_loop() -> asyncio.AbstractEventLoop:
    return asyncio.SelectorEventLoop()


if __name__ == "__main__":
    config = uvicorn.Config(
        "app.main:app",
        host="127.0.0.1",
        port=int(sys.argv[1]) if len(sys.argv) > 1 else 8001,
        reload=False,
    )
    server = uvicorn.Server(config)
    if sys.platform == "win32":
        asyncio.run(server.serve(), loop_factory=_selector_event_loop)
    else:
        server.run()
