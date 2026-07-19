from __future__ import annotations

from sqlalchemy.types import UserDefinedType


class Vector(UserDefinedType):
    """CockroachDB / pgvector-compatible VECTOR(n) column type."""

    cache_ok = True

    def __init__(self, dimensions: int) -> None:
        if dimensions <= 0:
            raise ValueError("VECTOR dimensions must be positive")
        self.dimensions = dimensions

    def get_col_spec(self, **_: object) -> str:
        return f"VECTOR({self.dimensions})"

    def bind_processor(self, dialect: object):  # noqa: ANN001
        def process(value: object) -> object:
            if value is None:
                return None
            if isinstance(value, (list, tuple)):
                return "[" + ",".join(str(float(v)) for v in value) + "]"
            return value

        return process

    def result_processor(self, dialect: object, coltype: object):  # noqa: ANN001
        def process(value: object) -> object:
            return value

        return process
