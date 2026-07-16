"""CockroachDB-safe helpers shared by Alembic migrations."""

from __future__ import annotations

from sqlalchemy.types import UserDefinedType


class Vector(UserDefinedType):
    """CockroachDB VECTOR(n) column type for migrations."""

    cache_ok = True

    def __init__(self, dimensions: int) -> None:
        if dimensions <= 0:
            raise ValueError("VECTOR dimensions must be positive")
        self.dimensions = dimensions

    def get_col_spec(self, **_: object) -> str:
        return f"VECTOR({self.dimensions})"
