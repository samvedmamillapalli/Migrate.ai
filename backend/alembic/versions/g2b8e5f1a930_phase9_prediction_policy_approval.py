"""phase9_prediction_policy_approval

Phase 9: extend predictions and migration_runs for policy, prediction
explainability, and recommendations; add approvals table.

Revision ID: g2b8e5f1a930
Revises: f1a9d4e6c820
Create Date: 2026-07-18 14:00:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "g2b8e5f1a930"
down_revision: Union[str, Sequence[str], None] = "f1a9d4e6c820"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # --- predictions: Phase 9 confidence + versioning + structured explanation ---
    op.add_column(
        "predictions",
        sa.Column(
            "raw_confidence_score",
            sa.Float(),
            nullable=False,
            server_default="0",
        ),
    )
    op.add_column(
        "predictions",
        sa.Column(
            "confidence_adjustments",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
    )
    op.add_column(
        "predictions",
        sa.Column(
            "key_assumptions",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
    )
    op.add_column(
        "predictions",
        sa.Column(
            "uncertainty_notes",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
    )
    op.add_column(
        "predictions",
        sa.Column(
            "model_version",
            sa.String(length=256),
            nullable=False,
            server_default="unknown",
        ),
    )
    op.add_column(
        "predictions",
        sa.Column(
            "prompt_template_version",
            sa.String(length=64),
            nullable=False,
            server_default="unknown",
        ),
    )
    # Backfill raw_confidence from existing confidence_score where present.
    op.execute(
        "UPDATE predictions SET raw_confidence_score = confidence_score "
        "WHERE raw_confidence_score = 0"
    )

    # --- migration_runs: policy + recommendation + explainability ---
    op.add_column(
        "migration_runs",
        sa.Column("risk_flags", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )
    op.add_column(
        "migration_runs",
        sa.Column("compatibility_risk", sa.String(length=16), nullable=True),
    )
    op.add_column(
        "migration_runs",
        sa.Column("requires_expand_contract", sa.Boolean(), nullable=True),
    )
    op.add_column(
        "migration_runs",
        sa.Column("requires_manual_review", sa.Boolean(), nullable=True),
    )
    op.add_column(
        "migration_runs",
        sa.Column("policy_decision", sa.String(length=32), nullable=True),
    )
    op.add_column(
        "migration_runs",
        sa.Column(
            "parsed_statement_types",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
    )
    op.add_column(
        "migration_runs",
        sa.Column(
            "recommendation",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
    )
    op.add_column(
        "migration_runs",
        sa.Column(
            "explainability",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
    )
    op.add_column(
        "migration_runs",
        sa.Column("prediction_scale_tier", sa.String(length=32), nullable=True),
    )
    op.create_index(
        "ix_migration_runs_policy_decision",
        "migration_runs",
        ["policy_decision"],
        unique=False,
    )

    # --- approvals table ---
    op.create_table(
        "approvals",
        sa.Column(
            "id",
            sa.Uuid(),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("migration_run_id", sa.Uuid(), nullable=False),
        sa.Column("approver_identity", sa.String(length=256), nullable=False),
        sa.Column("decision", sa.String(length=32), nullable=False),
        sa.Column("override_rationale", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(
            ["migration_run_id"],
            ["migration_runs.id"],
            name="fk_approvals_migration_run_id",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "migration_run_id",
            name="uq_approvals_migration_run_id",
        ),
    )
    op.create_index("ix_approvals_decision", "approvals", ["decision"], unique=False)
    op.create_index(
        "ix_approvals_created_at",
        "approvals",
        ["created_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_approvals_created_at", table_name="approvals")
    op.drop_index("ix_approvals_decision", table_name="approvals")
    op.drop_table("approvals")

    op.drop_index(
        "ix_migration_runs_policy_decision",
        table_name="migration_runs",
    )
    op.drop_column("migration_runs", "prediction_scale_tier")
    op.drop_column("migration_runs", "explainability")
    op.drop_column("migration_runs", "recommendation")
    op.drop_column("migration_runs", "parsed_statement_types")
    op.drop_column("migration_runs", "policy_decision")
    op.drop_column("migration_runs", "requires_manual_review")
    op.drop_column("migration_runs", "requires_expand_contract")
    op.drop_column("migration_runs", "compatibility_risk")
    op.drop_column("migration_runs", "risk_flags")

    op.drop_column("predictions", "prompt_template_version")
    op.drop_column("predictions", "model_version")
    op.drop_column("predictions", "uncertainty_notes")
    op.drop_column("predictions", "key_assumptions")
    op.drop_column("predictions", "confidence_adjustments")
    op.drop_column("predictions", "raw_confidence_score")
