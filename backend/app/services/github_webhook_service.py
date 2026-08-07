"""GitHub `pull_request` webhook handling — docs/FUTURE_GITHUB_INTEGRATION_PLAN.md.

Pipeline: verify signature -> parse event -> detect a migration file via the
linked workspace's configured glob -> resolve workspace -> create a
MigrationRun -> discover -> predict -> stop at awaiting_approval, exactly
like every other run (the plan's approval model (a): no auto-approval, a
human approves via a link into the app using the existing
``POST /runs/{id}/approve`` flow). Posting the initial PR comment/check run
happens from ``PredictionPipelineService._notify_prediction_ready`` (mirrors
how Slack's "prediction ready" notification already hooks that exact point);
this service only creates the run and the ``GithubPullRequestLink`` row that
tells that hook where to post.

Every step here is best-effort in the same sense the Slack integration is:
a GitHub API failure must never crash the webhook handler, and is instead
logged, and — for failures the PR author needs to know about (SQL
extraction failed, no migration file matched, no linked workspace, discover/
predict errored) — reported back as a plain PR comment explaining why no
prediction was produced, rather than silently doing nothing.
"""

from __future__ import annotations

import fnmatch
import hashlib
import hmac
import re
from typing import Any

from fastapi import Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.core.exceptions import GithubApiError, GithubWebhookError, ValidationError
from app.core.logging import get_logger
from app.database.models import MigrationRun
from app.database.models.github_pull_request_link import GithubPullRequestLink
from app.database.models.workspace import Workspace
from app.repositories.github_pull_request_link_repository import (
    GithubPullRequestLinkRepository,
)
from app.repositories.workspace_repository import WorkspaceRepository
from app.services.connection_secrets import load_connection
from app.services.github_app_client import GithubAppClient
from app.services.migration_run_service import MigrationRunService
from app.services.prediction_pipeline_service import PredictionPipelineService
from app.services.schema_discovery_service import SchemaDiscoveryService

logger = get_logger(__name__)

# Only these pull_request actions can introduce a new/changed migration file
# worth (re-)predicting. `synchronize` fires on every new push to the PR
# branch, matching "re-run automatically when the PR is updated."
_RELEVANT_PR_ACTIONS = {"opened", "synchronize", "reopened"}

_OP_EXECUTE_RE = re.compile(
    r'op\.execute\(\s*(?:"""(?P<triple_d>.*?)"""|\'\'\'(?P<triple_s>.*?)\'\'\''
    r'|"(?P<double>(?:[^"\\]|\\.)*)"|\'(?P<single>(?:[^\'\\]|\\.)*)\')\s*\)',
    re.DOTALL,
)


def verify_webhook_signature(
    payload_body: bytes, signature_header: str | None, webhook_secret: str
) -> None:
    """Verify GitHub's ``X-Hub-Signature-256`` header (HMAC-SHA256 over the
    raw request body). Raises ``GithubWebhookError`` on any mismatch,
    missing header, or missing secret configuration — a webhook route must
    never trust a payload that fails this check.
    """
    if not webhook_secret:
        raise GithubWebhookError(
            "GITHUB_WEBHOOK_SECRET is not configured; refusing to process "
            "an unverifiable webhook"
        )
    if not signature_header or not signature_header.startswith("sha256="):
        raise GithubWebhookError("Missing or malformed X-Hub-Signature-256 header")

    expected = hmac.new(
        webhook_secret.encode("utf-8"), payload_body, hashlib.sha256
    ).hexdigest()
    provided = signature_header.removeprefix("sha256=")
    if not hmac.compare_digest(expected, provided):
        raise GithubWebhookError("Webhook signature verification failed")


def find_migration_file(paths: list[str], glob_pattern: str) -> list[str]:
    """Repo-relative paths matching the workspace's configured glob,
    preserving the order GitHub returned them in."""
    return [p for p in paths if fnmatch.fnmatch(p, glob_pattern)]


def extract_migration_sql(file_content: str, file_path: str) -> str:
    """Best-effort single-SQL-statement extraction from a matched file.

    ``.sql`` files are used as-is. Python migration files (this project's own
    Alembic convention, and the default heuristic) are scanned for
    ``op.execute(...)`` string literals — the only shape of an Alembic file
    that contains directly-executable raw SQL. This deliberately does not
    attempt to reconstruct SQL from schema-builder calls like
    ``op.add_column`` / ``op.create_table`` — turning that into a general
    migration-framework SQL synthesizer is explicitly out of scope for this
    plan (docs/FUTURE_GITHUB_INTEGRATION_PLAN.md's "Proposed Detection
    Heuristic" section), not something to half-solve here.

    Raises ``ValidationError`` when no extractable SQL is found, which the
    caller turns into an explanatory PR comment rather than a crash.
    """
    if file_path.endswith(".sql"):
        sql = file_content.strip()
        if not sql:
            raise ValidationError(f"{file_path} is empty")
        return sql

    matches = _OP_EXECUTE_RE.findall(file_content)
    statements = [
        next(g for g in groups if g) for groups in matches if any(groups)
    ]
    if not statements:
        raise ValidationError(
            f"No op.execute(...) raw SQL found in {file_path}. Migration "
            "Oracle currently requires the migration to contain at least one "
            "directly-executable raw SQL statement; schema-builder-only "
            "migrations (op.add_column, op.create_table, ...) aren't "
            "supported yet."
        )
    if len(statements) > 1:
        logger.info(
            "Multiple op.execute() calls found; using the first one",
            extra={"file_path": file_path, "count": len(statements)},
        )
    return statements[0].strip()


class GithubWebhookService:
    """Orchestrates one `pull_request` webhook end to end."""

    def __init__(
        self,
        *,
        session: AsyncSession,
        workspace_repository: WorkspaceRepository,
        pr_link_repository: GithubPullRequestLinkRepository,
        migration_run_service: MigrationRunService,
        discovery_service: SchemaDiscoveryService,
        prediction_service: PredictionPipelineService,
        settings: Settings,
    ) -> None:
        self._session = session
        self._workspaces = workspace_repository
        self._pr_links = pr_link_repository
        self._runs = migration_run_service
        self._discovery = discovery_service
        self._prediction = prediction_service
        self._settings = settings

    def _client(self) -> GithubAppClient:
        app_id = (self._settings.github_app_id or "").strip()
        private_key = (
            self._settings.github_app_private_key.get_secret_value()
            if self._settings.github_app_private_key
            else ""
        )
        if not app_id or not private_key:
            raise GithubApiError(
                "GITHUB_APP_ID / GITHUB_APP_PRIVATE_KEY are not configured"
            )
        return GithubAppClient(
            app_id=app_id,
            private_key_pem=private_key,
            api_base_url=self._settings.github_api_base_url,
        )

    async def handle_pull_request_event(
        self, request: Request, payload: dict[str, Any]
    ) -> MigrationRun | None:
        """Returns the created MigrationRun, or None when the event was a
        no-op (wrong action, no linked workspace, no matching migration
        file)."""
        action = str(payload.get("action") or "")
        if action not in _RELEVANT_PR_ACTIONS:
            logger.info("Ignoring pull_request action", extra={"action": action})
            return None

        repository = payload.get("repository") or {}
        pull_request = payload.get("pull_request") or {}
        installation = payload.get("installation") or {}

        repo_full_name = str(repository.get("full_name") or "")
        installation_id = installation.get("id")
        pr_number = pull_request.get("number")
        head_sha = ((pull_request.get("head") or {}).get("sha")) or ""
        pr_author_login = ((pull_request.get("user") or {}).get("login")) or None

        if not (repo_full_name and installation_id and pr_number and head_sha):
            raise GithubWebhookError(
                "pull_request payload missing repository/installation/PR number/head sha"
            )

        existing = await self._pr_links.get_by_pr_head_sha(
            repo_full_name, int(pr_number), head_sha
        )
        if existing is not None:
            # Redelivery (manual, or GitHub retrying a delivery it recorded
            # as failed) — the same commit already has a run. Creating a
            # second one would mean a duplicate shadow cluster's real cost
            # and a duplicate PR comment.
            logger.info(
                "PR head sha already has a run; ignoring redelivered webhook",
                extra={
                    "repo_full_name": repo_full_name,
                    "pr_number": pr_number,
                    "head_sha": head_sha,
                    "existing_run_id": str(existing.migration_run_id),
                },
            )
            return None

        workspace = await self._workspaces.get_by_github_repo_full_name(repo_full_name)
        if workspace is None:
            logger.info(
                "No workspace linked to repo; ignoring webhook",
                extra={"repo_full_name": repo_full_name},
            )
            return None

        client = self._client()
        token = await client.get_installation_token(int(installation_id))

        changed_files = await client.list_pull_request_files(
            token, repo_full_name, int(pr_number)
        )
        matched = find_migration_file(changed_files, workspace.github_migration_glob)
        if not matched:
            logger.info(
                "No file in this PR matched the migration glob; ignoring",
                extra={
                    "repo_full_name": repo_full_name,
                    "pr_number": pr_number,
                    "glob": workspace.github_migration_glob,
                },
            )
            return None
        if len(matched) > 1:
            logger.info(
                "Multiple files matched the migration glob; using the first",
                extra={"repo_full_name": repo_full_name, "matched": matched},
            )
        migration_file_path = matched[0]

        file_content = await client.get_file_content(
            token, repo_full_name, migration_file_path, head_sha
        )

        try:
            migration_sql = extract_migration_sql(file_content, migration_file_path)
        except ValidationError as exc:
            await self._post_explanatory_comment(
                client,
                token,
                repo_full_name,
                int(pr_number),
                title="Migration Oracle could not analyze this migration",
                body=str(exc.message),
            )
            return None

        if not workspace.connection_secret_arn:
            await self._post_explanatory_comment(
                client,
                token,
                repo_full_name,
                int(pr_number),
                title="Migration Oracle could not run a prediction",
                body=(
                    f"Workspace **{workspace.name}** is linked to this repo but has "
                    "no stored database connection yet. Add one in the workspace "
                    "settings, then push a new commit to re-trigger this check."
                ),
            )
            return None

        run = await self._runs.create_migration_run(
            migration_sql,
            owner_identity=workspace.owner_identity,
            workspace_id=workspace.id,
            run_kind="github_pr",
        )

        # The link row must exist and be COMMITTED before predict runs.
        # PredictionPipelineService fires its "prediction ready" hook inside
        # run_prediction_pipeline, and GithubNotificationService resolves
        # where to post by looking this row up by run id — created any later
        # and that lookup finds nothing, so the PR comment and check run are
        # silently skipped. (Exactly that bug shipped once: a real PR
        # produced a correct run held at awaiting_approval, with
        # check_run_id/initial_comment_id both NULL and nothing posted.)
        link = GithubPullRequestLink(
            migration_run_id=run.id,
            repo_full_name=repo_full_name,
            pr_number=int(pr_number),
            installation_id=int(installation_id),
            head_sha=head_sha,
            pr_author_login=pr_author_login,
        )
        await self._pr_links.create(link)
        await self._session.commit()

        return await self._discover_and_predict(
            request,
            run=run,
            connection_secret_arn=workspace.connection_secret_arn,
        )

    async def _discover_and_predict(
        self,
        request: Request,
        *,
        run: MigrationRun,
        connection_secret_arn: str,
    ) -> MigrationRun:
        connection = await load_connection(request, connection_secret_arn)
        run = await self._discovery.discover_and_persist(
            run.id,
            connection,
            connection_secret_arn=connection_secret_arn,
        )
        return await self._prediction.run_prediction_pipeline(run.id)

    async def _post_explanatory_comment(
        self,
        client: GithubAppClient,
        token: str,
        repo_full_name: str,
        pr_number: int,
        *,
        title: str,
        body: str,
    ) -> None:
        try:
            await client.post_issue_comment(
                token,
                repo_full_name,
                pr_number,
                f"### {title}\n\n{body}",
            )
        except GithubApiError:
            logger.warning(
                "Failed to post explanatory PR comment",
                extra={"repo_full_name": repo_full_name, "pr_number": pr_number},
                exc_info=True,
            )


__all__ = [
    "GithubWebhookService",
    "verify_webhook_signature",
    "find_migration_file",
    "extract_migration_sql",
]
