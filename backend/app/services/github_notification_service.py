"""Posts prediction and terminal results back to a linked GitHub PR —
docs/FUTURE_GITHUB_INTEGRATION_PLAN.md's "Proposed Result Reporting" section.

Mirrors ``SlackNotificationService``'s posture exactly: every method is
fire-and-forget best-effort — a GitHub lookup, token, or API failure is
logged and returned as ``False`` so a notification issue never affects the
prediction or grading pipeline that triggered it.

Check-run conclusions are deliberately never ``failure`` or
``action_required`` here — the plan's resolved Open Question #4 is
"warning comment only, don't block the merge, at least at first." The
actual pass/fail signal lives in the comment text, not in something GitHub
branch protection could use to block a merge.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings, get_settings
from app.core.exceptions import GithubApiError
from app.core.logging import get_logger
from app.database.models import MigrationRun
from app.repositories.github_pull_request_link_repository import (
    GithubPullRequestLinkRepository,
)
from app.services.github_app_client import GithubAppClient
from app.services.slack_helpers import derive_migration_name

logger = get_logger(__name__)

_CHECK_RUN_NAME = "Migration Oracle"

_POLICY_LABEL = {
    "allow": "✅ Allow",
    "allow_with_warning": "⚠️ Allow with warning",
    "block": "⛔ Block (overridable)",
}
# Never "failure"/"action_required" — see module docstring.
_POLICY_CONCLUSION = {
    "allow": "success",
    "allow_with_warning": "neutral",
    "block": "neutral",
}


class GithubNotificationService:
    def __init__(
        self,
        *,
        pr_link_repository: GithubPullRequestLinkRepository,
        session: AsyncSession,
        settings: Settings | None = None,
    ) -> None:
        self._pr_links = pr_link_repository
        self._session = session
        self._settings = settings or get_settings()

    def _client(self) -> GithubAppClient | None:
        app_id = (self._settings.github_app_id or "").strip()
        private_key = (
            self._settings.github_app_private_key.get_secret_value()
            if self._settings.github_app_private_key
            else ""
        )
        if not app_id or not private_key:
            return None
        return GithubAppClient(
            app_id=app_id,
            private_key_pem=private_key,
            api_base_url=self._settings.github_api_base_url,
        )

    async def send_prediction_ready(self, run: MigrationRun) -> bool:
        """Post the initial prediction/recommendation comment + check run."""
        link = await self._pr_links.get_by_migration_run_id(run.id)
        if link is None:
            return False
        client = self._client()
        if client is None:
            logger.warning(
                "GitHub App not configured; skipping PR notification",
                extra={"run_id": str(run.id)},
            )
            return False

        try:
            token = await client.get_installation_token(link.installation_id)
            body = self._build_prediction_comment(run)
            comment_id = await client.post_issue_comment(
                token, link.repo_full_name, link.pr_number, body
            )
            policy_value = run.policy_decision.value if run.policy_decision else "allow"
            check_run_id = await client.create_check_run(
                token,
                link.repo_full_name,
                name=_CHECK_RUN_NAME,
                head_sha=link.head_sha,
                status="completed",
                conclusion=_POLICY_CONCLUSION.get(policy_value, "neutral"),
                title=_POLICY_LABEL.get(policy_value, policy_value),
                summary=(
                    "Prediction ready. Awaiting human approval — "
                    f"see the PR comment for the review link."
                ),
            )
            link.initial_comment_id = comment_id
            link.check_run_id = check_run_id
            await self._pr_links.update(link)
            await self._session.commit()
            logger.info(
                "Posted GitHub prediction comment + check run",
                extra={
                    "run_id": str(run.id),
                    "repo_full_name": link.repo_full_name,
                    "pr_number": link.pr_number,
                },
            )
            return True
        except GithubApiError:
            logger.warning(
                "GitHub prediction_ready notification failed",
                extra={"run_id": str(run.id)},
                exc_info=True,
            )
            return False
        except Exception:  # noqa: BLE001 - best-effort, must not raise
            logger.warning(
                "GitHub prediction_ready notification failed unexpectedly",
                extra={"run_id": str(run.id)},
                exc_info=True,
            )
            return False

    async def send_terminal_result(self, run: MigrationRun) -> bool:
        """Post the terminal predicted-vs-measured follow-up comment.

        Idempotent via ``terminal_comment_posted_at`` — a later re-sync of an
        already-terminal run must not post twice, same guard the Slack
        terminal hook relies on via ``just_became_terminal``.
        """
        link = await self._pr_links.get_by_migration_run_id(run.id)
        if link is None or link.terminal_comment_posted_at is not None:
            return False
        client = self._client()
        if client is None:
            return False

        try:
            token = await client.get_installation_token(link.installation_id)
            body = self._build_terminal_comment(run)
            await client.post_issue_comment(token, link.repo_full_name, link.pr_number, body)
            if link.check_run_id is not None:
                conclusion = "success" if self._measured_success(run) else "neutral"
                await client.update_check_run(
                    token,
                    link.repo_full_name,
                    link.check_run_id,
                    status="completed",
                    conclusion=conclusion,
                    title="Shadow run complete",
                    summary="Predicted vs. measured results posted to this PR.",
                )
            link.terminal_comment_posted_at = datetime.now(UTC)
            await self._pr_links.update(link)
            await self._session.commit()
            logger.info(
                "Posted GitHub terminal result comment",
                extra={"run_id": str(run.id), "repo_full_name": link.repo_full_name},
            )
            return True
        except GithubApiError:
            logger.warning(
                "GitHub terminal notification failed",
                extra={"run_id": str(run.id)},
                exc_info=True,
            )
            return False
        except Exception:  # noqa: BLE001 - best-effort, must not raise
            logger.warning(
                "GitHub terminal notification failed unexpectedly",
                extra={"run_id": str(run.id)},
                exc_info=True,
            )
            return False

    # --- comment builders ------------------------------------------------

    def _frontend_link(self, run: MigrationRun) -> str:
        frontend = (self._settings.frontend_url or "").rstrip("/")
        return f"{frontend}/dashboard/migrations/{run.id}" if frontend else ""

    def _build_prediction_comment(self, run: MigrationRun) -> str:
        migration_name = derive_migration_name(run.migration_sql)
        prediction = run.prediction
        recommendation = run.recommendation or {}
        policy_value = run.policy_decision.value if run.policy_decision else "unknown"
        risk_flags = run.risk_flags or []

        lines = [
            "## 🔮 Migration Oracle prediction",
            "",
            f"**Migration:** `{migration_name}`",
            "",
        ]
        if prediction is not None:
            lines += [
                "| Metric | Predicted |",
                "| --- | --- |",
                f"| Duration | {prediction.estimated_duration_seconds:.1f}s |",
                f"| Storage growth | {prediction.estimated_storage_mb:.1f} MB |",
                f"| Rollback risk | {prediction.rollback_risk.value if hasattr(prediction.rollback_risk, 'value') else prediction.rollback_risk} |",
                f"| Confidence | {prediction.confidence_score:.0%} |",
                "",
            ]
        lines.append(
            f"**Policy decision:** {_POLICY_LABEL.get(policy_value, policy_value)}"
        )
        if risk_flags:
            lines.append("")
            lines.append("**Risk flags:**")
            for flag in risk_flags:
                title = flag.get("title") or flag.get("rule_id") or "finding"
                explanation = flag.get("explanation") or ""
                lines.append(f"- **{title}** — {explanation}")

        if recommendation:
            lines += [
                "",
                f"**Recommended strategy:** {recommendation.get('recommended_strategy', '')}",
                "",
                "**Rollout steps:**",
            ]
            for step in recommendation.get("rollout_steps") or []:
                lines.append(f"1. {step}")
            rollback_guidance = recommendation.get("rollback_guidance")
            if rollback_guidance:
                lines += ["", f"**Rollback guidance:** {rollback_guidance}"]

        link = self._frontend_link(run)
        lines += [
            "",
            "---",
            (
                f"[Review and approve in Migration Oracle]({link})"
                if link
                else "Review and approve this run in Migration Oracle."
            ),
            (
                "This is advisory only — Migration Oracle never blocks this "
                "merge; a human always approves before anything runs against "
                "a shadow database."
            ),
        ]
        return "\n".join(lines)

    def _measured_success(self, run: MigrationRun) -> bool:
        result = run.execution_result
        return bool(result is not None and result.success)

    def _build_terminal_comment(self, run: MigrationRun) -> str:
        prediction = run.prediction
        result = run.execution_result
        grade = run.grade

        lines = ["## 📊 Migration Oracle — measured outcome", ""]
        if result is None:
            lines.append(
                "The shadow run ended without a recorded execution result "
                f"(status: `{run.status.value}`)."
            )
            return "\n".join(lines)

        lines += [
            f"**Outcome:** {'✅ Succeeded' if result.success else '❌ Failed'}",
            "",
            "| Metric | Predicted | Measured |",
            "| --- | --- | --- |",
        ]
        if prediction is not None:
            lines.append(
                f"| Duration | {prediction.estimated_duration_seconds:.1f}s | "
                f"{result.actual_duration_seconds:.1f}s |"
            )
            lines.append(
                f"| Storage growth | {prediction.estimated_storage_mb:.1f} MB | "
                f"{result.actual_storage_mb:.1f} MB |"
            )
        else:
            lines.append(
                f"| Duration | — | {result.actual_duration_seconds:.1f}s |"
            )
            lines.append(
                f"| Storage growth | — | {result.actual_storage_mb:.1f} MB |"
            )
        if result.error_message:
            lines += ["", f"**Error:** {result.error_message}"]

        if grade is not None:
            lines += [
                "",
                f"**Prediction accuracy score:** {grade.scalar_accuracy_score:.0%} "
                f"({grade.outcome_class})",
            ]
            if grade.lessons_learned:
                lines += ["", f"**Lesson learned:** {grade.lessons_learned}"]

        link = self._frontend_link(run)
        if link:
            lines += ["", f"[View full details in Migration Oracle]({link})"]
        return "\n".join(lines)


__all__ = ["GithubNotificationService"]
