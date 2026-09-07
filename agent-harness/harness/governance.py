"""Policy matching and approval primitives for governed step actions."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from enum import Enum
from typing import Any


VALID_RISKS = {"low", "medium", "high", "critical"}


@dataclass(frozen=True)
class PolicyRule:
    """A rule that controls whether an action needs human approval."""

    action_pattern: str
    risk: str
    requires_approval: bool

    def __post_init__(self) -> None:
        if not isinstance(self.action_pattern, str) or not self.action_pattern:
            raise ValueError("action_pattern must be a non-empty string.")
        if "*" in self.action_pattern[:-1]:
            raise ValueError("action_pattern only supports a trailing '*' wildcard.")
        if self.risk not in VALID_RISKS:
            raise ValueError(f"risk must be one of {sorted(VALID_RISKS)}.")


class PolicyDecision(str, Enum):
    """The outcome of checking an action against configured policy rules."""

    ALLOW = "ALLOW"
    REQUIRES_APPROVAL = "REQUIRES_APPROVAL"


class PolicyViolation(RuntimeError):
    """Raised when approval is denied for a governed action."""

    def __init__(self, step_name: str, action: str) -> None:
        self.step_name = step_name
        self.action = action
        super().__init__(f"Policy denied action '{action}' for step '{step_name}'.")


ApprovalCallback = Callable[[str, str], bool]


class PolicyEngine:
    """Choose policy decisions and obtain approval for actions that require it."""

    def __init__(
        self,
        rules: list[PolicyRule | Mapping[str, Any]],
        approval_callback: ApprovalCallback | None = None,
    ) -> None:
        self.rules = [self._coerce_rule(rule) for rule in rules]
        self.approval_callback = approval_callback or self._prompt_for_approval

    def check(self, action: str) -> PolicyDecision:
        """Return the decision from the most specific matching policy rule."""
        rule = self._matching_rule(action)
        if rule is None or not rule.requires_approval:
            return PolicyDecision.ALLOW
        return PolicyDecision.REQUIRES_APPROVAL

    def request_approval(self, action: str) -> bool:
        """Ask the configured approver whether a matching action may proceed."""
        rule = self._matching_rule(action)
        risk = rule.risk if rule is not None else "low"
        return bool(self.approval_callback(action, risk))

    def _matching_rule(self, action: str) -> PolicyRule | None:
        matches = [rule for rule in self.rules if self._matches(rule.action_pattern, action)]
        if not matches:
            return None
        return max(matches, key=lambda rule: self._specificity(rule.action_pattern))

    @staticmethod
    def _coerce_rule(rule: PolicyRule | Mapping[str, Any]) -> PolicyRule:
        if isinstance(rule, PolicyRule):
            return rule
        if isinstance(rule, Mapping):
            return PolicyRule(**rule)
        raise TypeError("Each policy rule must be a PolicyRule or mapping.")

    @staticmethod
    def _matches(pattern: str, action: str) -> bool:
        if pattern.endswith("*"):
            return action.startswith(pattern[:-1])
        return action == pattern

    @staticmethod
    def _specificity(pattern: str) -> int:
        return len(pattern.rstrip("*"))

    @staticmethod
    def _prompt_for_approval(action: str, risk: str) -> bool:
        print(f"Approval required for action '{action}' (risk: {risk}).")
        return input("Approve? [y/N]: ").strip().lower() in {"y", "yes"}
