"""Start the Migration Oracle API (Windows-safe event loop).

On Windows, psycopg async requires SelectorEventLoop. The ``uvicorn`` executable
is often missing from PATH; use ``python run_server.py`` instead.

Usage (from backend/):

  python run_server.py            # 127.0.0.1:8000
  python run_server.py 8003       # explicit port
  API_PORT=8003 python run_server.py

The port matters because the web app reads NEXT_PUBLIC_API_BASE_URL from
frontend/oracle/apps/web/.env.local — start this on whatever port that names,
or the UI will talk to a different (possibly stale) server.
"""

from __future__ import annotations

import asyncio
import os
import selectors
import sys


def _selector_loop_factory() -> asyncio.AbstractEventLoop:
    """Force SelectorEventLoop on Windows (psycopg incompatible with Proactor)."""
    return asyncio.SelectorEventLoop(selectors.SelectSelector())


def main() -> None:
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

    import uvicorn

    loop: object
    if sys.platform == "win32":
        loop = _selector_loop_factory
    else:
        loop = "asyncio"

    port = 8000
    if len(sys.argv) > 1:
        port = int(sys.argv[1])
    elif os.environ.get("API_PORT"):
        port = int(os.environ["API_PORT"])

    uvicorn.run(
        "app.main:app",
        host="127.0.0.1",
        port=port,
        reload=False,
        loop=loop,  # type: ignore[arg-type]
    )


if __name__ == "__main__":
    main()
