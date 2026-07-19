"""Start the Migration Oracle API (Windows-safe event loop).

On Windows, psycopg async requires SelectorEventLoop. The ``uvicorn`` executable
is often missing from PATH; use ``python run_server.py`` instead.

Usage (from backend/):

  python run_server.py
"""

from __future__ import annotations

import asyncio
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

    uvicorn.run(
        "app.main:app",
        host="127.0.0.1",
        port=8000,
        reload=False,
        loop=loop,  # type: ignore[arg-type]
    )


if __name__ == "__main__":
    main()
