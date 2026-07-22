#!/usr/bin/env python3
"""Print corpus / memory-store health as JSON (no browser required).

Usage (from backend/):
  python scripts/corpus_health.py
"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


async def main() -> int:
    from app.config import get_settings
    from app.database import DatabaseSessionManager
    from app.memory.corpus_health import fetch_corpus_health

    settings = get_settings()
    database = DatabaseSessionManager(settings.database_url.get_secret_value())
    health: dict = {}
    async for session in database.session():
        health = await fetch_corpus_health(session)
        print(json.dumps(health, indent=2, default=str))
        break
    await database.close()
    return 0 if health.get("healthy") else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
