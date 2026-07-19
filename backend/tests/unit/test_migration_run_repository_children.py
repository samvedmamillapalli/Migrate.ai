"""Regression: grade/memory visible after same-session write when children were None."""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.database.models import MigrationRun
from app.repositories.migration_run_repository import MigrationRunRepository


@pytest.mark.asyncio
async def test_get_by_id_load_children_expires_stale_none_relationships() -> None:
    """Reproduce identity-map bug: children loaded as None, then written later.

    ``get_by_id(..., load_children=True)`` must expire stale relationship
    attributes so selectinload can see newly committed grade/memory rows.
    """
    run_id = uuid.uuid4()
    session = AsyncMock()

    stale = MagicMock(spec=MigrationRun)
    # Simulate selectinload having populated grade/memory as None earlier.
    stale.__dict__ = {
        "id": run_id,
        "grade": None,
        "memory": None,
        "prediction": None,
        "execution_result": None,
        "learned_outcome": None,
        "shadow_cluster": None,
        "approval": None,
    }
    session.get = AsyncMock(return_value=stale)
    session.expire = MagicMock()

    refreshed = MagicMock(spec=MigrationRun)
    refreshed.grade = MagicMock()
    refreshed.memory = MagicMock()
    execute_result = MagicMock()
    execute_result.scalar_one_or_none.return_value = refreshed
    session.execute = AsyncMock(return_value=execute_result)

    repo = MigrationRunRepository(session)
    got = await repo.get_by_id(run_id, load_children=True)

    assert got is refreshed
    assert got.grade is not None
    assert got.memory is not None
    expired_attrs = []
    for call in session.expire.call_args_list:
        attrs = call.args[1]
        expired_attrs.extend(attrs)
    assert "grade" in expired_attrs
    assert "memory" in expired_attrs
    # populate_existing must be set so the identity map is refreshed.
    assert session.execute.await_count == 1
    exec_args = session.execute.await_args
    statement = exec_args.args[0]
    assert statement is not None
