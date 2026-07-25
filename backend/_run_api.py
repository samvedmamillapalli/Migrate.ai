"""Windows-safe uvicorn entrypoint (SelectorEventLoop for psycopg)."""

from __future__ import annotations

import asyncio
import sys

if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

import uvicorn

if __name__ == "__main__":
    uvicorn.run(
        "app.main:app",
        host="127.0.0.1",
        port=int(sys.argv[1]) if len(sys.argv) > 1 else 8001,
        reload=False,
    )
