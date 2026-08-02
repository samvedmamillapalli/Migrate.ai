#!/usr/bin/env python3
"""Embed a curated subset of the CockroachDB Agent Skills Repo into
``cockroachdb_skill_docs`` for retrieval via CockroachDB's Distributed Vector
Index. See docs/cockroach_hookup.md §5.

Reads SKILL.md files vendored at the repo root via
``npx skills add cockroachlabs/cockroachdb-skills`` (``.agents/skills/<slug>/SKILL.md``).
A curated subset, not the whole ~30-skill repo — see _CURATED_SKILLS below for
which and why.

Run from backend/:
  python scripts/ingest_cockroachdb_skills.py
  python scripts/ingest_cockroachdb_skills.py --verify-retrieval
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path
from typing import Any

import yaml

if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

SKILLS_DIR = ROOT.parent / ".agents" / "skills"
GITHUB_BASE = "https://github.com/cockroachlabs/cockroachdb-skills/blob/main/skills"

# Curated, not exhaustive — see docs/cockroach_hookup.md §5 "Concrete build"
# step 3: a focused set directly relevant to schema migrations is more
# defensible than a bulk dump of all ~30 skills nobody reviewed. Each maps to
# its real category directory in the source repo (for source_url + citation).
_CURATED_SKILLS: list[tuple[str, str]] = [
    ("analyzing-schema-change-storage-risk", "cockroachdb-observability-and-diagnostics"),
    ("hardening-user-privileges", "cockroachdb-security-and-governance"),
    ("reviewing-cluster-health", "cockroachdb-operations-and-lifecycle"),
    ("analyzing-range-distribution", "cockroachdb-observability-and-diagnostics"),
    ("cockroachdb-sql", "cockroachdb-query-and-schema-design"),
    ("auditing-table-statistics", "cockroachdb-observability-and-diagnostics"),
    ("monitoring-background-jobs", "cockroachdb-observability-and-diagnostics"),
]


def _extract_h1_title(body: str, fallback: str) -> str:
    for line in body.splitlines():
        stripped = line.strip()
        if stripped.startswith("# "):
            return stripped[2:].strip()
    return fallback


def _parse_skill_md(path: Path) -> dict[str, Any]:
    raw = path.read_text(encoding="utf-8")
    if not raw.startswith("---"):
        raise ValueError(f"{path} has no YAML frontmatter")
    _, fm, body = raw.split("---", 2)
    frontmatter = yaml.safe_load(fm) or {}
    body = body.strip()
    # `name:` in frontmatter is the slug (e.g. "hardening-user-privileges"),
    # not a display title — the human-readable title is the first H1 in the
    # body (e.g. "# Hardening User Privileges").
    return {
        "name": _extract_h1_title(body, fallback=frontmatter.get("name", path.parent.name)),
        "description": frontmatter.get("description", ""),
        "body": body,
    }


def _load_curated() -> list[dict[str, Any]]:
    loaded: list[dict[str, Any]] = []
    for slug, category in _CURATED_SKILLS:
        path = SKILLS_DIR / slug / "SKILL.md"
        if not path.exists():
            print(f"SKIP {slug}: {path} not found (run `npx skills add "
                  f"cockroachlabs/cockroachdb-skills` at the repo root first)")
            continue
        parsed = _parse_skill_md(path)
        loaded.append(
            {
                "skill_slug": slug,
                "category": category,
                "title": parsed["name"],
                "description": parsed["description"],
                "body": parsed["body"],
                "source_url": f"{GITHUB_BASE}/{category}/{slug}/SKILL.md",
            }
        )
    return loaded


async def _ingest() -> int:
    from sqlalchemy import select

    from app.aws.config import get_aws_settings
    from app.config import get_settings
    from app.database import DatabaseSessionManager
    from app.database.models import CockroachDBSkillDoc
    from app.memory.constants import EMBEDDING_STATUS_FAILED, EMBEDDING_STATUS_READY
    from app.memory.embedding_client import (
        AwsTitanEmbeddingClient,
        EmbeddingAccessError,
        EmbeddingInvocationError,
        vector_to_literal,
    )

    settings = get_settings()
    aws = get_aws_settings()
    embed_client = AwsTitanEmbeddingClient(settings=aws)
    model_id = aws.bedrock_embedding_model_id

    records = _load_curated()
    print(f"Curated skills found on disk: {len(records)}/{len(_CURATED_SKILLS)}")
    if not records:
        print("Nothing to ingest.")
        return 1

    db = DatabaseSessionManager(settings.database_url.get_secret_value())
    ready = 0
    failed = 0
    async for session in db.session():
        for rec in records:
            # embed_text: title + description carry the "when to use this"
            # signal that matters most for retrieval matching a migration's
            # mechanism; the full body is stored for citation/display but
            # would dilute the embedding with prose the query never mentions.
            embed_text = f"{rec['title']}\n\n{rec['description']}"
            embedding_literal: str | None = None
            status = EMBEDDING_STATUS_FAILED
            error: str | None = None
            try:
                vector = embed_client.embed(embed_text, model_id=model_id)
                embedding_literal = vector_to_literal(vector)
                status = EMBEDDING_STATUS_READY
                ready += 1
            except (EmbeddingAccessError, EmbeddingInvocationError, Exception) as exc:
                error = f"{type(exc).__name__}: {exc}"[:2000]
                failed += 1
                print(f"  EMBED FAILED {rec['skill_slug']}: {error}")

            existing = (
                await session.execute(
                    select(CockroachDBSkillDoc).where(
                        CockroachDBSkillDoc.skill_slug == rec["skill_slug"]
                    )
                )
            ).scalar_one_or_none()
            payload = dict(
                category=rec["category"],
                title=rec["title"],
                description=rec["description"],
                body=rec["body"],
                source_url=rec["source_url"],
                embedding=embedding_literal,
                embedding_status=status,
                embedding_error=error,
                embedding_model_id=model_id,
            )
            if existing is None:
                entity = CockroachDBSkillDoc(skill_slug=rec["skill_slug"], **payload)
                session.add(entity)
            else:
                for key, value in payload.items():
                    setattr(existing, key, value)
            await session.commit()
            print(f"  {rec['skill_slug']}: {status}")
        break
    await db.close()

    print(f"\nDone. ready={ready} failed={failed}")
    return 0 if failed == 0 else 1


async def _verify_retrieval() -> None:
    from app.aws.config import get_aws_settings
    from app.config import get_settings
    from app.database import DatabaseSessionManager
    from app.memory.embedding_client import AwsTitanEmbeddingClient, vector_to_literal
    from app.repositories.skill_doc_repository import SkillDocRepository

    settings = get_settings()
    aws = get_aws_settings()
    db = DatabaseSessionManager(settings.database_url.get_secret_value())
    query = "creating a unique index on a large table, worried about backfill storage"
    async for session in db.session():
        embed_client = AwsTitanEmbeddingClient(settings=aws)
        vector = embed_client.embed(query)
        rows, index_used = await SkillDocRepository(session).semantic_search(
            query_vector_literal=vector_to_literal(vector),
            limit=3,
        )
        print(f"\n=== Retrieval check: {query!r} ===")
        print(f"index_used={index_used} hits={len(rows)}")
        for doc, sim in rows:
            print(f"  [{sim:.3f}] {doc.skill_slug} — {doc.title}")
        break
    await db.close()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--verify-retrieval", action="store_true")
    args = parser.parse_args()

    if args.verify_retrieval:
        asyncio.run(_verify_retrieval())
        return 0
    return asyncio.run(_ingest())


if __name__ == "__main__":
    raise SystemExit(main())
