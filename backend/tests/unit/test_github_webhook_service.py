"""GithubWebhookService orchestration — docs/FUTURE_GITHUB_INTEGRATION_PLAN.md.

Covers the no-op paths (wrong action, no linked workspace, no matching
migration file, no stored connection) and the happy path (create run ->
discover -> predict -> persist the PR link), all with the GitHub API client
and connection loading mocked out so no network/DB is touched.
"""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.config import Settings
from app.core.exceptions import GithubWebhookError
from app.database.models import Workspace
from app.services.github_webhook_service import GithubWebhookService

_PR_PAYLOAD = {
    "action": "opened",
    "repository": {"full_name": "acme/widgets"},
    "installation": {"id": 12345},
    "pull_request": {
        "number": 42,
        "head": {"sha": "deadbeef"},
        "user": {"login": "octocat"},
    },
}


def _settings() -> Settings:
    return Settings(
        database_url="postgresql://u:p@h:26257/d",
        github_app_id="123",
        github_app_private_key="not-a-real-key",
        github_webhook_secret="test-secret",
    )


def _workspace(**overrides) -> Workspace:
    defaults = dict(
        id=uuid.uuid4(),
        owner_identity="owner-1",
        name="Default",
        connection_secret_arn="arn:aws:secretsmanager:workspace-secret",
        connection_label=None,
        is_default=False,
        github_repo_full_name="acme/widgets",
        github_migration_glob="backend/alembic/versions/*.py",
    )
    defaults.update(overrides)
    return Workspace(**defaults)


@pytest.fixture
def workspace_repository() -> AsyncMock:
    return AsyncMock()


@pytest.fixture
def pr_link_repository() -> AsyncMock:
    mock = AsyncMock()
    # Default: this commit has no run yet. Tests exercising the redelivery
    # guard override this explicitly.
    mock.get_by_pr_head_sha.return_value = None
    return mock


@pytest.fixture
def migration_run_service() -> AsyncMock:
    return AsyncMock()


@pytest.fixture
def discovery_service() -> AsyncMock:
    return AsyncMock()


@pytest.fixture
def prediction_service() -> AsyncMock:
    return AsyncMock()


@pytest.fixture
def session() -> AsyncMock:
    mock = AsyncMock()
    mock.commit = AsyncMock()
    return mock


@pytest.fixture
def service(
    session, workspace_repository, pr_link_repository, migration_run_service,
    discovery_service, prediction_service,
) -> GithubWebhookService:
    return GithubWebhookService(
        session=session,
        workspace_repository=workspace_repository,
        pr_link_repository=pr_link_repository,
        migration_run_service=migration_run_service,
        discovery_service=discovery_service,
        prediction_service=prediction_service,
        settings=_settings(),
    )


def _mock_client(*, files: list[str], file_content: str = "") -> MagicMock:
    client = MagicMock()
    client.get_installation_token = AsyncMock(return_value="install-token")
    client.list_pull_request_files = AsyncMock(return_value=files)
    client.get_file_content = AsyncMock(return_value=file_content)
    client.post_issue_comment = AsyncMock(return_value=999)
    return client


@pytest.mark.asyncio
async def test_ignores_irrelevant_action(service: GithubWebhookService) -> None:
    payload = {**_PR_PAYLOAD, "action": "closed"}
    result = await service.handle_pull_request_event(MagicMock(), payload)
    assert result is None


@pytest.mark.asyncio
async def test_ignores_repo_with_no_linked_workspace(
    service: GithubWebhookService, workspace_repository: AsyncMock
) -> None:
    workspace_repository.get_by_github_repo_full_name.return_value = None
    result = await service.handle_pull_request_event(MagicMock(), _PR_PAYLOAD)
    assert result is None


@pytest.mark.asyncio
async def test_raises_on_incomplete_payload(service: GithubWebhookService) -> None:
    payload = {"action": "opened", "repository": {}, "pull_request": {}}
    with pytest.raises(GithubWebhookError):
        await service.handle_pull_request_event(MagicMock(), payload)


@pytest.mark.asyncio
async def test_redelivered_webhook_for_same_head_sha_creates_no_duplicate_run(
    service: GithubWebhookService,
    workspace_repository: AsyncMock,
    pr_link_repository: AsyncMock,
    migration_run_service: AsyncMock,
) -> None:
    """GitHub redelivers webhooks — manually from the deliveries UI, and
    automatically after a delivery it recorded as failed (which happened for
    real: the first live PR timed out GitHub's 10s limit while the pipeline
    ran inline). Every redelivery carries the same head sha, so without this
    guard each one would create a duplicate MigrationRun: a duplicate shadow
    cluster's real cost plus a duplicate PR comment.
    """
    pr_link_repository.get_by_pr_head_sha.return_value = MagicMock(
        migration_run_id=uuid.uuid4()
    )

    result = await service.handle_pull_request_event(MagicMock(), _PR_PAYLOAD)

    assert result is None
    migration_run_service.create_migration_run.assert_not_awaited()
    # Short-circuits before any GitHub API call, so a redelivery storm can't
    # burn installation-token requests either.
    workspace_repository.get_by_github_repo_full_name.assert_not_awaited()


@pytest.mark.asyncio
async def test_no_op_when_no_file_matches_glob(
    service: GithubWebhookService, workspace_repository: AsyncMock
) -> None:
    workspace_repository.get_by_github_repo_full_name.return_value = _workspace()
    mock_client = _mock_client(files=["README.md", "app/main.py"])
    with patch.object(service, "_client", return_value=mock_client):
        result = await service.handle_pull_request_event(MagicMock(), _PR_PAYLOAD)
    assert result is None


@pytest.mark.asyncio
async def test_posts_comment_when_connection_missing(
    service: GithubWebhookService, workspace_repository: AsyncMock
) -> None:
    workspace_repository.get_by_github_repo_full_name.return_value = _workspace(
        connection_secret_arn=None
    )
    mock_client = _mock_client(
        files=["backend/alembic/versions/abc_migration.py"],
        file_content="def upgrade():\n    op.execute('ALTER TABLE t ADD COLUMN c INT;')\n",
    )
    with patch.object(service, "_client", return_value=mock_client):
        result = await service.handle_pull_request_event(MagicMock(), _PR_PAYLOAD)
    assert result is None
    mock_client.post_issue_comment.assert_awaited_once()


@pytest.mark.asyncio
async def test_happy_path_creates_run_and_pr_link(
    service: GithubWebhookService,
    workspace_repository: AsyncMock,
    migration_run_service: AsyncMock,
    discovery_service: AsyncMock,
    prediction_service: AsyncMock,
    pr_link_repository: AsyncMock,
    session: AsyncMock,
) -> None:
    workspace = _workspace()
    workspace_repository.get_by_github_repo_full_name.return_value = workspace

    created_run = MagicMock(id=uuid.uuid4())
    migration_run_service.create_migration_run.return_value = created_run
    discovery_service.discover_and_persist.return_value = created_run
    prediction_service.run_prediction_pipeline.return_value = created_run

    mock_client = _mock_client(
        files=["backend/alembic/versions/abc_migration.py"],
        file_content=(
            "def upgrade():\n"
            "    op.execute('ALTER TABLE t ADD COLUMN c INT;')\n"
        ),
    )

    with (
        patch.object(service, "_client", return_value=mock_client),
        patch(
            "app.services.github_webhook_service.load_connection",
            new=AsyncMock(return_value=MagicMock()),
        ),
    ):
        result = await service.handle_pull_request_event(MagicMock(), _PR_PAYLOAD)

    assert result is created_run
    migration_run_service.create_migration_run.assert_awaited_once()
    kwargs = migration_run_service.create_migration_run.await_args.kwargs
    assert kwargs["owner_identity"] == workspace.owner_identity
    assert kwargs["workspace_id"] == workspace.id
    assert kwargs["run_kind"] == "github_pr"
    assert "ALTER TABLE t ADD COLUMN c INT;" in (
        migration_run_service.create_migration_run.await_args.args[0]
    )

    discovery_service.discover_and_persist.assert_awaited_once()
    prediction_service.run_prediction_pipeline.assert_awaited_once_with(created_run.id)

    pr_link_repository.create.assert_awaited_once()
    created_link = pr_link_repository.create.await_args.args[0]
    assert created_link.migration_run_id == created_run.id
    assert created_link.repo_full_name == "acme/widgets"
    assert created_link.pr_number == 42
    assert created_link.installation_id == 12345
    assert created_link.head_sha == "deadbeef"
    assert created_link.pr_author_login == "octocat"
    session.commit.assert_awaited()


@pytest.mark.asyncio
async def test_pr_link_is_committed_before_prediction_runs(
    service: GithubWebhookService,
    workspace_repository: AsyncMock,
    migration_run_service: AsyncMock,
    discovery_service: AsyncMock,
    prediction_service: AsyncMock,
    pr_link_repository: AsyncMock,
    session: AsyncMock,
) -> None:
    """Regression: the PR-link row must exist and be committed BEFORE
    run_prediction_pipeline is called.

    PredictionPipelineService fires its prediction-ready hook inside that
    call, and GithubNotificationService finds where to post by looking this
    row up by run id. Created any later, the lookup returns None and the PR
    comment + check run are silently skipped — which is exactly what
    happened on the first real PR: a correct run held at awaiting_approval
    with check_run_id and initial_comment_id both NULL, and nothing posted
    to GitHub.
    """
    workspace_repository.get_by_github_repo_full_name.return_value = _workspace()
    created_run = MagicMock(id=uuid.uuid4())
    migration_run_service.create_migration_run.return_value = created_run
    discovery_service.discover_and_persist.return_value = created_run
    prediction_service.run_prediction_pipeline.return_value = created_run

    calls: list[str] = []
    pr_link_repository.create.side_effect = lambda *a, **k: calls.append("link_created")
    session.commit.side_effect = lambda *a, **k: calls.append("commit")
    prediction_service.run_prediction_pipeline.side_effect = (
        lambda *a, **k: calls.append("predict") or created_run
    )

    mock_client = _mock_client(
        files=["backend/alembic/versions/abc_migration.py"],
        file_content="def upgrade():\n    op.execute('ALTER TABLE t ADD COLUMN c INT;')\n",
    )
    with (
        patch.object(service, "_client", return_value=mock_client),
        patch(
            "app.services.github_webhook_service.load_connection",
            new=AsyncMock(return_value=MagicMock()),
        ),
    ):
        await service.handle_pull_request_event(MagicMock(), _PR_PAYLOAD)

    assert "link_created" in calls and "predict" in calls
    assert calls.index("link_created") < calls.index("predict"), (
        f"PR link must be created before prediction; got order: {calls}"
    )
    assert calls.index("commit") < calls.index("predict"), (
        f"PR link must be COMMITTED before prediction; got order: {calls}"
    )
