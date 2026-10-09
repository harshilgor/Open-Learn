import pytest
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from backend.app.agent_execution.contracts import Command, InputAnswer, InputRequest, Message, TaskDependency
from backend.app.agent_execution.kernel import (
    AgentKernel,
    AskUserDecision,
    CallToolDecision,
    CompletionEvaluator,
    DecisionLimits,
    DecisionState,
    KernelError,
    ToolRegistry,
    ToolResult,
    ToolSpec,
)


class EchoInput(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)
    task_id: str = Field(alias="taskId")


def test_decision_contracts_reject_untrusted_or_malformed_shapes():
    ask = AgentKernel.parse_decision({"kind": "ask_user", "question": "Which unit?", "options": ["cm", "m"]})
    assert isinstance(ask, AskUserDecision)
    assert ask.input_kind == "text"  # choices are suggestions until input_kind=choice is explicit

    with pytest.raises(KernelError, match="model_decision_invalid"):
        AgentKernel.parse_decision({"kind": "call_tool", "tool": "os.system", "arguments": {}, "authority": "root"})
    with pytest.raises(KernelError, match="choice_options_required"):
        AgentKernel.parse_decision({"kind": "ask_user", "question": "Pick", "inputKind": "choice"})
    with pytest.raises(KernelError, match="wait_target_required"):
        AgentKernel.parse_decision({"kind": "wait", "reason": "dependency"})


def test_tool_registry_is_allowlisted_typed_and_capability_scoped():
    called = []
    registry = ToolRegistry([
        ToolSpec("analysis.run", EchoInput, {"analysis"}, lambda args: called.append(args.task_id) or ToolResult(status="completed"))
    ])
    result = registry.invoke(CallToolDecision(kind="call_tool", tool="analysis.run", arguments={"taskId": "task-1"}), {"analysis"})
    assert result.status == "completed" and called == ["task-1"]
    with pytest.raises(KernelError, match="tool_unavailable"):
        registry.invoke(CallToolDecision(kind="call_tool", tool="unknown", arguments={}), {"analysis"})
    with pytest.raises(KernelError, match="tool_capability_denied"):
        registry.invoke(CallToolDecision(kind="call_tool", tool="analysis.run", arguments={"taskId": "task-2"}), {"research"})
    with pytest.raises(KernelError, match="tool_arguments_invalid"):
        registry.invoke(CallToolDecision(kind="call_tool", tool="analysis.run", arguments={"taskId": "task-3", "shell": True}), {"analysis"})


def test_kernel_enforces_decision_tool_and_repeated_no_progress_ceilings():
    registry = ToolRegistry([
        ToolSpec("analysis.run", EchoInput, {"analysis"}, lambda _: ToolResult(status="completed", progressKey="same-result"))
    ])
    kernel = AgentKernel(registry, DecisionLimits(maxDecisions=3, maxToolCalls=3, maxRepeatedNoProgress=1))
    decision = {"kind": "call_tool", "tool": "analysis.run", "arguments": {"taskId": "task-1"}}
    _, _, state = kernel.step(decision, capabilities={"analysis"})
    _, _, state = kernel.step(decision, state=state, capabilities={"analysis"})
    with pytest.raises(KernelError, match="no_progress"):
        kernel.step(decision, state=state, capabilities={"analysis"})

    no_tool = AgentKernel(ToolRegistry(), DecisionLimits(maxDecisions=1, maxToolCalls=0))
    _, _, state = no_tool.step({"kind": "respond", "text": "Done"})
    with pytest.raises(KernelError, match="decision_budget_exhausted"):
        no_tool.step({"kind": "respond", "text": "Again"}, state=state)


def test_completion_evaluator_checks_required_outputs_sources_and_unknowns():
    requirements = {
        "requestedOutputs": ["report.csv"],
        "checks": [
            {"id": "cited", "kind": "source_present", "value": "source-1"},
            {"id": "verified", "kind": "check_passes", "value": "calculation"},
        ],
    }
    incomplete = CompletionEvaluator.evaluate(requirements, [], [], {"checks": [{"criterion": "calculation", "status": "pass"}]})
    assert incomplete["status"] == "failed"
    verified = CompletionEvaluator.evaluate(
        requirements,
        [{"name": "report.csv"}],
        [{"id": "source-1"}],
        {"checks": [{"criterion": "calculation", "status": "pass"}]},
    )
    assert verified["status"] == "verified"
    partial = CompletionEvaluator.evaluate(requirements, [{"name": "report.csv"}], [{"id": "source-1"}], {})
    assert partial["status"] == "partial"


def test_generic_input_and_dependency_contracts_are_revisioned_and_typed():
    request = InputRequest(requestId="request-1", taskId="task-1", revision=1, question="Upload your CSV", inputKind="file")
    assert request.state == "open"
    with pytest.raises(ValidationError):
        InputRequest(requestId="request-2", taskId="task-1", revision=1, question="Choose", inputKind="choice")
    with pytest.raises(ValidationError):
        InputRequest(requestId="request-3", taskId="task-1", revision=1, question="Upload", inputKind="file", options=["skip"])
    with pytest.raises(ValidationError):
        InputAnswer(text=" ")
    dependency = TaskDependency(id="artifact-1", kind="artifact", sourceId="task-1", sourceRevision=2)
    assert dependency.status == "pending" and dependency.source_revision == 2

    reply = Message(clientMessageId="m-1", sessionId="s-1", text="cm", targetTaskId="task-1", replyToRequestId="request-1", expectedRevision=2, expectedRequestRevision=1)
    assert reply.expected_revision == 2
    with pytest.raises(ValidationError):
        Message(clientMessageId="m-2", sessionId="s-1", text="cm", targetTaskId="task-1", replyToRequestId="request-1", expectedRevision=2)
    with pytest.raises(ValidationError):
        Command(commandId="c-1", action="answer_input", expectedRevision=2, requestId="request-1", answer={"text": "cm"})
