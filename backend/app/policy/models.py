"""Pydantic models for the deterministic risk and policy layer."""

from __future__ import annotations

import enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator


class FindingSeverity(str, enum.Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class PolicyDecisionValue(str, enum.Enum):
    ALLOW = "allow"
    ALLOW_WITH_WARNING = "allow_with_warning"
    BLOCK = "block"


class CompatibilityRiskValue(str, enum.Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


_SEVERITY_RANK = {
    FindingSeverity.LOW: 0,
    FindingSeverity.MEDIUM: 1,
    FindingSeverity.HIGH: 2,
}

_DECISION_RANK = {
    PolicyDecisionValue.ALLOW: 0,
    PolicyDecisionValue.ALLOW_WITH_WARNING: 1,
    PolicyDecisionValue.BLOCK: 2,
}

_COMPAT_RANK = {
    CompatibilityRiskValue.LOW: 0,
    CompatibilityRiskValue.MEDIUM: 1,
    CompatibilityRiskValue.HIGH: 2,
}


class RiskFinding(BaseModel):
    """Structured finding from a single deterministic rule hit."""

    model_config = ConfigDict(frozen=True)

    rule_id: str
    title: str
    severity: FindingSeverity
    objects: list[str] = Field(default_factory=list)
    explanation: str
    policy_decision: PolicyDecisionValue
    row_count: int | None = None
    row_count_known: bool = True


class PolicyAnalysisResult(BaseModel):
    """Full output of the deterministic layer for one migration submission."""

    model_config = ConfigDict(frozen=True)

    risk_flags: list[RiskFinding]
    compatibility_risk: CompatibilityRiskValue
    requires_expand_contract: bool
    requires_manual_review: bool
    policy_decision: PolicyDecisionValue
    parsed_statement_types: list[str]
    parse_failed: bool = False

    def to_persistable(self) -> dict[str, Any]:
        return {
            "risk_flags": [f.model_dump(mode="json") for f in self.risk_flags],
            "compatibility_risk": self.compatibility_risk.value,
            "requires_expand_contract": self.requires_expand_contract,
            "requires_manual_review": self.requires_manual_review,
            "policy_decision": self.policy_decision.value,
            "parsed_statement_types": list(self.parsed_statement_types),
            "parse_failed": self.parse_failed,
        }


class RuleConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    enabled: bool = True
    title: str
    base_severity: FindingSeverity
    policy_decision: PolicyDecisionValue
    requires_manual_review: bool = False
    requires_expand_contract: bool = False
    compatibility_risk: CompatibilityRiskValue = CompatibilityRiskValue.LOW
    escalate_by_row_count: bool = False
    explanation: str


class RowCountThresholds(BaseModel):
    model_config = ConfigDict(extra="forbid")

    medium: int = Field(ge=0)
    high: int = Field(ge=0)

    @field_validator("high")
    @classmethod
    def high_ge_medium(cls, value: int, info: Any) -> int:
        medium = info.data.get("medium")
        if medium is not None and value < medium:
            raise ValueError("row_count_thresholds.high must be >= medium")
        return value


class PolicyDefaults(BaseModel):
    model_config = ConfigDict(extra="forbid")

    policy_decision: PolicyDecisionValue = PolicyDecisionValue.ALLOW_WITH_WARNING
    row_count_thresholds: RowCountThresholds


class PolicyFile(BaseModel):
    """Validated shape of the committed policy YAML file."""

    model_config = ConfigDict(extra="forbid")

    version: int = Field(ge=1)
    defaults: PolicyDefaults
    decision_precedence: list[PolicyDecisionValue]
    rules: dict[str, RuleConfig]

    @field_validator("decision_precedence")
    @classmethod
    def validate_precedence(
        cls,
        value: list[PolicyDecisionValue],
    ) -> list[PolicyDecisionValue]:
        expected = {
            PolicyDecisionValue.ALLOW,
            PolicyDecisionValue.ALLOW_WITH_WARNING,
            PolicyDecisionValue.BLOCK,
        }
        if set(value) != expected or len(value) != 3:
            raise ValueError(
                "decision_precedence must list allow, allow_with_warning, and block exactly once"
            )
        return value


def max_severity(*values: FindingSeverity) -> FindingSeverity:
    return max(values, key=lambda s: _SEVERITY_RANK[s])


def max_decision(*values: PolicyDecisionValue) -> PolicyDecisionValue:
    return max(values, key=lambda d: _DECISION_RANK[d])


def max_compatibility(*values: CompatibilityRiskValue) -> CompatibilityRiskValue:
    return max(values, key=lambda c: _COMPAT_RANK[c])


def escalate_severity(
    base: FindingSeverity,
    row_count: int | None,
    thresholds: RowCountThresholds,
) -> FindingSeverity:
    """Raise severity when row counts cross configured thresholds."""
    if row_count is None:
        return base
    if row_count >= thresholds.high:
        return max_severity(base, FindingSeverity.HIGH)
    if row_count >= thresholds.medium:
        return max_severity(base, FindingSeverity.MEDIUM)
    return base
