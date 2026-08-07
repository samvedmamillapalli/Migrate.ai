"""Links a MigrationRun to the GitHub pull request that triggered it —
docs/FUTURE_GITHUB_INTEGRATION_PLAN.md.

Created once, at webhook-receipt time, by ``GithubWebhookService``. Read
back by the prediction and terminal notification hooks
(``PredictionPipelineService._notify_prediction_ready`` /
``WorkflowOrchestrationService._notify_terminal``) to know whether — and
where — to post a result back to GitHub. A run with no linked PR (the
common case, a UI-created run) simply has no row here.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import BigInteger, DateTime, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.base import Base
from app.database.mixins import TimestampMixin, UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from app.database.models.migration_run import MigrationRun


class GithubPullRequestLink(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "github_pull_request_links"
    __table_args__ = (
        UniqueConstraint(
            "migration_run_id",
            name="uq_github_pr_links_migration_run_id",
        ),
    )

    migration_run_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("migration_runs.id", ondelete="CASCADE"),
        nullable=False,
    )
    repo_full_name: Mapped[str] = mapped_column(String(256), nullable=False)
    pr_number: Mapped[int] = mapped_column(Integer, nullable=False)
    # GitHub installation ids and check-run/comment ids exceed 32-bit range.
    installation_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    head_sha: Mapped[str] = mapped_column(String(64), nullable=False)
    pr_author_login: Mapped[str | None] = mapped_column(String(256), nullable=True)
    check_run_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    initial_comment_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    # Guards the terminal predicted-vs-measured comment against being posted
    # twice, same "just_became_terminal" idea as the Slack terminal hook.
    terminal_comment_posted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    migration_run: Mapped[MigrationRun] = relationship(
        "MigrationRun",
        back_populates="github_pr_link",
    )

    def __repr__(self) -> str:
        return (
            f"GithubPullRequestLink(id={self.id!s}, "
            f"repo={self.repo_full_name!r}, pr={self.pr_number!r})"
        )
