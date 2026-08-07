"""Persistence operations for GithubPullRequestLink entities."""

from __future__ import annotations

import uuid

from sqlalchemy import select

from app.database.models.github_pull_request_link import GithubPullRequestLink
from app.repositories.base import BaseRepository


class GithubPullRequestLinkRepository(BaseRepository[GithubPullRequestLink]):
    model = GithubPullRequestLink

    async def get_by_migration_run_id(
        self, migration_run_id: uuid.UUID
    ) -> GithubPullRequestLink | None:
        query = select(GithubPullRequestLink).where(
            GithubPullRequestLink.migration_run_id == migration_run_id
        )
        result = await self._session.execute(query)
        return result.scalar_one_or_none()

    async def get_by_pr_head_sha(
        self, repo_full_name: str, pr_number: int, head_sha: str
    ) -> GithubPullRequestLink | None:
        """Existing link for this exact commit on this exact PR.

        Used as an idempotency guard: GitHub redelivers webhooks (manually
        from the deliveries UI, or automatically after a failed delivery),
        and every redelivery carries the same head sha. Without this check
        each redelivery would create a duplicate MigrationRun — a duplicate
        shadow cluster's worth of real cost, and a second PR comment.
        """
        query = select(GithubPullRequestLink).where(
            GithubPullRequestLink.repo_full_name == repo_full_name,
            GithubPullRequestLink.pr_number == pr_number,
            GithubPullRequestLink.head_sha == head_sha,
        )
        result = await self._session.execute(query)
        return result.scalars().first()
