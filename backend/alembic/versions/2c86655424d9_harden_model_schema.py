"""harden_model_schema

Revision ID: 2c86655424d9
Revises: e2582b1052d5
Create Date: 2026-07-17 01:27:20.600063

"""

from typing import Sequence, Union

from alembic import op

revision: str = "2c86655424d9"
down_revision: Union[str, Sequence[str], None] = "e2582b1052d5"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Unique constraints are named in e2582b1052d5 for deterministic installs.
    # This revision only adds query indexes required by the ORM models.
    op.create_index(
        "ix_migration_runs_created_at",
        "migration_runs",
        ["created_at"],
        unique=False,
    )
    op.create_index(
        "ix_predictions_created_at",
        "predictions",
        ["created_at"],
        unique=False,
    )
    op.create_index(
        "ix_predictions_rollback_risk",
        "predictions",
        ["rollback_risk"],
        unique=False,
    )
    op.create_index(
        "ix_verifications_created_at",
        "verifications",
        ["created_at"],
        unique=False,
    )
    op.create_index(
        "ix_verifications_timed_out",
        "verifications",
        ["timed_out"],
        unique=False,
    )
    op.create_index(
        "ix_memories_created_at",
        "memories",
        ["created_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_memories_created_at", table_name="memories")
    op.drop_index("ix_verifications_timed_out", table_name="verifications")
    op.drop_index("ix_verifications_created_at", table_name="verifications")
    op.drop_index("ix_predictions_rollback_risk", table_name="predictions")
    op.drop_index("ix_predictions_created_at", table_name="predictions")
    op.drop_index("ix_migration_runs_created_at", table_name="migration_runs")
