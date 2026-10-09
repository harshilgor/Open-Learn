"""Typed, bounded decision and output-verification kernel for agent tasks.

The kernel is deliberately provider-neutral. Models may propose a decision, but
only registered application tools and existing authorization/usage services can
perform work. A decision budget is a behavioral ceiling; monetary reservations
remain owned by the unified usage ledger.
"""
from __future__ import annotations

import hashlib
import json
import time
from typing import Annotated, Any, Callable, Literal, Union

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, ValidationError


class KernelContract(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)


class CallToolDecision(KernelContract):
    kind: Literal["call_tool"]
    tool: str = Field(min_length=1, max_length=80)
    arguments: dict[str, Any] = Field(default_factory=dict)


class AskUserDecision(KernelContract):
    kind: Literal["ask_user"]
    question: str = Field(min_length=1, max_length=1200)
    input_kind: Literal["text", "choice", "file", "voice_transcript", "confirmation"] = Field(default="text", alias="inputKind")
    required: bool = True
    options: list[str] = Field(default_factory=list, max_length=12)


class DelegateDecision(KernelContract):
    kind: Literal["delegate"]
    goal: str = Field(min_length=1, max_length=2000)
    tool_allowlist: list[str] = Field(default_factory=list, alias="toolAllowlist", max_length=12)
    source_ids: list[str] = Field(default_factory=list, alias="sourceIds", max_length=40)
    deadline_seconds: int = Field(default=300, alias="deadlineSeconds", ge=1, le=3600)
    budget_calls: int = Field(default=4, alias="budgetCalls", ge=0, le=12)
    budget_tokens: int = Field(default=4000, alias="budgetTokens", ge=0, le=25000)
    acceptance_checks: list[str] = Field(default_factory=list, alias="acceptanceChecks", max_length=12)


class WaitDecision(KernelContract):
    kind: Literal["wait"]
    reason: Literal["input", "tool", "dependency", "resource", "approval"]
    dependency_id: str | None = Field(default=None, alias="dependencyId", max_length=160)
    wake_at: float | None = Field(default=None, alias="wakeAt")


class FinalClaim(KernelContract):
    criterion: str = Field(min_length=1, max_length=100)
    status: Literal["pass", "fail", "unknown"]
    evidence_ids: list[str] = Field(default_factory=list, alias="evidenceIds", max_length=40)


class ProposeFinalDecision(KernelContract):
    kind: Literal["propose_final"]
    summary: str = Field(min_length=1, max_length=4000)
    requested_outputs: list[str] = Field(default_factory=list, alias="requestedOutputs", max_length=20)
    artifact_ids: list[str] = Field(default_factory=list, alias="artifactIds", max_length=40)
    source_ids: list[str] = Field(default_factory=list, alias="sourceIds", max_length=40)
    claimed_checks: list[FinalClaim] = Field(default_factory=list, alias="claimedChecks", max_length=30)


class RespondDecision(KernelContract):
    kind: Literal["respond"]
    text: str = Field(min_length=1, max_length=4000)


ModelDecision = Annotated[
    Union[
        CallToolDecision,
        AskUserDecision,
        DelegateDecision,
        WaitDecision,
        ProposeFinalDecision,
        RespondDecision,
    ],
    Field(discriminator="kind"),
]
_DECISION_ADAPTER = TypeAdapter(ModelDecision)


class ToolResult(KernelContract):
    """Bounded result envelope; provider/tool claims are evidence, not authority."""

    status: Literal["completed", "partial", "waiting", "failed", "proposed"]
    value: Any = None
    evidence_ids: list[str] = Field(default_factory=list, alias="evidenceIds", max_length=80)
    reason_code: str | None = Field(default=None, alias="reasonCode", max_length=100)
    progress_key: str | None = Field(default=None, alias="progressKey", max_length=200)


class DecisionLimits(KernelContract):
    max_decisions: int = Field(default=16, alias="maxDecisions", ge=1, le=64)
    max_tool_calls: int = Field(default=8, alias="maxToolCalls", ge=0, le=32)
    max_repeated_no_progress: int = Field(default=2, alias="maxRepeatedNoProgress", ge=0, le=4)


class DecisionState(KernelContract):
    decisions: int = 0
    tool_calls: int = Field(default=0, alias="toolCalls")
    repeated_no_progress: int = Field(default=0, alias="repeatedNoProgress")
    last_progress_key: str | None = Field(default=None, alias="lastProgressKey")
    recent_signatures: list[str] = Field(default_factory=list, alias="recentSignatures", max_length=8)


class ToolSpec:
    """Application-owned handler and typed argument schema for a capability."""

    def __init__(
        self,
        name: str,
        input_model: type[BaseModel],
        required_capabilities: set[str],
        handler: Callable[[BaseModel], ToolResult | dict[str, Any]],
    ):
        if not name or len(name) > 80 or not required_capabilities:
            raise ValueError("A tool needs a bounded name and at least one capability.")
        self.name = name
        self.input_model = input_model
        self.required_capabilities = frozenset(required_capabilities)
        self.handler = handler


class ToolRegistry:
    """Scoped registry. Model-provided names never become imports or commands."""

    def __init__(self, specs: list[ToolSpec] | None = None):
        self._tools: dict[str, ToolSpec] = {}
        for spec in specs or []:
            self.register(spec)

    def register(self, spec: ToolSpec) -> None:
        if spec.name in self._tools:
            raise ValueError("Tool names must be unique.")
        self._tools[spec.name] = spec

    def invoke(self, decision: CallToolDecision, capabilities: set[str]) -> ToolResult:
        spec = self._tools.get(decision.tool)
        if spec is None:
            raise KernelError("tool_unavailable")
        if not spec.required_capabilities.issubset(capabilities):
            raise KernelError("tool_capability_denied")
        try:
            arguments = spec.input_model.model_validate(decision.arguments)
        except (ValidationError, TypeError, ValueError):
            raise KernelError("tool_arguments_invalid") from None
        result = spec.handler(arguments)
        return result if isinstance(result, ToolResult) else ToolResult.model_validate(result)


class KernelError(ValueError):
    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


class AgentKernel:
    """Validate decisions, enforce task ceilings and stop repeated no-progress loops."""

    def __init__(self, registry: ToolRegistry, limits: DecisionLimits | None = None):
        self.registry = registry
        self.limits = limits or DecisionLimits()

    @staticmethod
    def parse_decision(value: Any) -> ModelDecision:
        try:
            decision = _DECISION_ADAPTER.validate_python(value)
        except (ValidationError, TypeError, ValueError):
            raise KernelError("model_decision_invalid") from None
        if isinstance(decision, WaitDecision):
            if decision.reason in {"dependency", "tool", "resource", "approval"} and not decision.dependency_id:
                raise KernelError("wait_target_required")
            if decision.reason == "input" and decision.dependency_id:
                raise KernelError("wait_target_invalid")
            if decision.wake_at is not None and decision.wake_at > time.time() + 7 * 86400:
                raise KernelError("wait_deadline_too_far")
        if isinstance(decision, AskUserDecision) and decision.input_kind == "choice" and not decision.options:
            raise KernelError("choice_options_required")
        if isinstance(decision, AskUserDecision) and decision.input_kind in {"file", "voice_transcript", "confirmation"} and decision.options:
            raise KernelError("unexpected_input_options")
        return decision

    def step(
        self,
        raw_decision: Any,
        *,
        state: DecisionState | dict[str, Any] | None = None,
        capabilities: set[str] | None = None,
    ) -> tuple[ModelDecision, ToolResult | None, DecisionState]:
        decision = self.parse_decision(raw_decision)
        current = state if isinstance(state, DecisionState) else DecisionState.model_validate(state or {})
        if current.decisions >= self.limits.max_decisions:
            raise KernelError("decision_budget_exhausted")
        signature = hashlib.sha256(
            json.dumps(decision.model_dump(mode="json", by_alias=True), sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
        repeated = current.recent_signatures.count(signature)
        next_state = current.model_copy(deep=True)
        next_state.decisions += 1
        next_state.recent_signatures = (next_state.recent_signatures + [signature])[-8:]
        result: ToolResult | None = None
        if isinstance(decision, CallToolDecision):
            if next_state.tool_calls >= self.limits.max_tool_calls:
                raise KernelError("tool_budget_exhausted")
            result = self.registry.invoke(decision, capabilities or set())
            next_state.tool_calls += 1
        if result and result.progress_key:
            if result.progress_key == current.last_progress_key:
                next_state.repeated_no_progress += 1
            else:
                next_state.repeated_no_progress = 0
            next_state.last_progress_key = result.progress_key
        elif isinstance(decision, CallToolDecision):
            next_state.repeated_no_progress = repeated + 1
        elif isinstance(decision, (WaitDecision, DelegateDecision)) and signature in current.recent_signatures:
            next_state.repeated_no_progress = current.repeated_no_progress + 1
        elif isinstance(decision, (WaitDecision, DelegateDecision)):
            next_state.repeated_no_progress = 0
        else:
            next_state.repeated_no_progress = 0
        if next_state.repeated_no_progress > self.limits.max_repeated_no_progress:
            raise KernelError("no_progress")
        return decision, result, next_state


class CompletionRequirement(KernelContract):
    id: str = Field(min_length=1, max_length=100)
    kind: Literal["artifact_present", "source_present", "check_passes"]
    value: str = Field(min_length=1, max_length=200)


class TaskRequirements(KernelContract):
    requested_outputs: list[str] = Field(default_factory=list, alias="requestedOutputs", max_length=20)
    checks: list[CompletionRequirement] = Field(default_factory=list, max_length=30)
    version: str = "completion-requirements-v1"


class CompletionEvaluator:
    """Evaluate only application-verifiable claims; unknown means partial."""

    @staticmethod
    def evaluate(requirements: TaskRequirements | dict[str, Any], outputs: list[dict[str, Any]], sources: list[dict[str, Any]], declared: dict[str, Any]) -> dict[str, Any]:
        req = requirements if isinstance(requirements, TaskRequirements) else TaskRequirements.model_validate(requirements)
        output_names = {str(item.get("name", "")) for item in outputs}
        source_ids = {str(item.get("id", item.get("sourceId", ""))) for item in sources}
        declared_checks = {str(item.get("criterion")): item for item in declared.get("checks", []) if isinstance(item, dict)}
        checks: list[dict[str, Any]] = []
        for name in req.requested_outputs:
            checks.append({"criterion": f"artifact:{name}", "status": "pass" if name in output_names else "fail"})
        for requirement in req.checks:
            status = "unknown"
            if requirement.kind == "artifact_present":
                status = "pass" if requirement.value in output_names else "fail"
            elif requirement.kind == "source_present":
                status = "pass" if requirement.value in source_ids else "fail"
            elif requirement.kind == "check_passes":
                status = declared_checks.get(requirement.value, {}).get("status", "unknown")
                if status not in {"pass", "fail", "unknown"}:
                    status = "unknown"
            checks.append({"criterion": requirement.id, "status": status})
        for item in declared.get("checks", []):
            if isinstance(item, dict):
                check_status = item.get("status") if item.get("status") in {"pass", "fail", "unknown"} else "unknown"
                checks.append({"criterion": str(item.get("criterion", "declared_check")), "status": check_status})
        if any(item["status"] == "fail" for item in checks):
            status = "failed"
        elif any(item["status"] == "unknown" for item in checks) or declared.get("partial") or declared.get("status") == "partial":
            status = "partial"
        else:
            status = "verified"
        return {"policyVersion": req.version, "status": status, "checks": checks,
                "limitations": list(declared.get("limitations", []))[:20]}
