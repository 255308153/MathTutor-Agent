from __future__ import annotations

from typing import Any, Literal, Sequence

from pydantic import BaseModel, Field

from .context import LearningTurnContext, RuntimeIntent


CapabilityExecutionMode = Literal["delegate_existing_learning_loop"]


class MathCapability(BaseModel):
    """Manifest entry for a mathematics-only runtime capability."""

    capability_id: str
    name: str
    purpose: str
    applicable_intents: tuple[RuntimeIntent, ...]
    expected_tools: tuple[str, ...]
    selection_reason: str
    execution_mode: CapabilityExecutionMode = "delegate_existing_learning_loop"
    state_write_policy: str = "capability_never_writes_learning_facts_directly"
    authority_boundaries: tuple[str, ...] = Field(
        default=(
            "KT facts are authoritative.",
            "Capability selection can influence orchestration, not mastery.",
            "Capability execution delegates to runtime-controlled tools or the existing learning loop.",
        )
    )

    def public_summary(self) -> dict[str, Any]:
        return {
            "capability_id": self.capability_id,
            "name": self.name,
            "purpose": self.purpose,
            "applicable_intents": list(self.applicable_intents),
            "expected_tools": list(self.expected_tools),
            "selection_reason": self.selection_reason,
            "execution_mode": self.execution_mode,
            "state_write_policy": self.state_write_policy,
            "authority_boundaries": list(self.authority_boundaries),
        }


class CapabilitySelection(BaseModel):
    intent: RuntimeIntent
    selected: bool
    fallback: bool
    reason: str
    capability: MathCapability | None = None
    delegated_to: str = "MathTutorLearningLoop"
    fallback_behavior: str = "use_existing_learning_loop"
    state_write_policy: str = "selection_is_read_only_and_does_not_write_learning_facts"

    def public_summary(self) -> dict[str, Any]:
        capability_summary = self.capability.public_summary() if self.capability else None
        return {
            "intent": self.intent,
            "selected": self.selected,
            "fallback": self.fallback,
            "reason": self.reason,
            "capability": capability_summary,
            "capability_id": (
                self.capability.capability_id if self.capability else "fallback_existing_learning_loop"
            ),
            "capability_name": self.capability.name if self.capability else "现有学习流 fallback",
            "expected_tools": (
                list(self.capability.expected_tools) if self.capability else []
            ),
            "execution_mode": (
                self.capability.execution_mode
                if self.capability
                else "delegate_existing_learning_loop"
            ),
            "delegated_to": self.delegated_to,
            "fallback_behavior": self.fallback_behavior,
            "state_write_policy": self.state_write_policy,
        }


class MathCapabilityRegistry:
    def __init__(self, capabilities: Sequence[MathCapability] | None = None) -> None:
        self._capabilities = tuple(
            DEFAULT_MATH_CAPABILITIES if capabilities is None else capabilities
        )

    def list_capabilities(self) -> list[MathCapability]:
        return list(self._capabilities)

    def manifest(self) -> list[dict[str, Any]]:
        return [capability.public_summary() for capability in self._capabilities]

    def select(self, context: LearningTurnContext) -> CapabilitySelection:
        for capability in self._capabilities:
            if context.intent in capability.applicable_intents:
                return CapabilitySelection(
                    intent=context.intent,
                    selected=True,
                    fallback=False,
                    capability=capability,
                    reason=(
                        f"intent={context.intent} 匹配数学能力 "
                        f"{capability.capability_id}；{capability.selection_reason}"
                    ),
                )
        return CapabilitySelection(
            intent=context.intent,
            selected=False,
            fallback=True,
            reason=(
                f"没有匹配 intent={context.intent} 的数学 capability；"
                "runtime 使用现有学习流 fallback。"
            ),
        )


DEFAULT_MATH_CAPABILITIES: tuple[MathCapability, ...] = (
    MathCapability(
        capability_id="math_answer_diagnosis",
        name="答题诊断与错因分析",
        purpose="围绕一次数学答题提交组织判分、KT 诊断、错因解释和下一题建议。",
        applicable_intents=("answer_submission",),
        expected_tools=(
            "content_repository",
            "kt_state_engine",
            "dgekt_attribution",
            "rag_retrieval",
            "student_memory",
            "teaching_planner",
            "question_recommender",
            "memory_writer",
        ),
        selection_reason="答题提交需要以 KT/DGEKT facts 为权威来源生成诊断与错因讲解。",
    ),
    MathCapability(
        capability_id="math_next_step_advice",
        name="下一步建议与复习规划",
        purpose="根据当前数学学习状态、薄弱点、记忆偏好和题库生成下一步练习建议。",
        applicable_intents=("next_step_advice",),
        expected_tools=(
            "kt_progress_reader",
            "rag_retrieval",
            "student_memory",
            "teaching_planner",
            "question_recommender",
        ),
        selection_reason="下一步请求需要读取学习状态并生成可解释推荐，但不能改写掌握度事实。",
    ),
    MathCapability(
        capability_id="math_concept_explanation",
        name="数学概念讲解与提示",
        purpose="为一般数学提问组织概念解释、提示策略和可追溯 RAG 支持。",
        applicable_intents=("general_chat",),
        expected_tools=(
            "kt_progress_reader",
            "rag_retrieval",
            "student_memory",
            "teaching_planner",
        ),
        selection_reason="一般数学对话优先组织讲解表达和证据引用，不直接更新 mastery。",
    ),
)


default_capability_registry = MathCapabilityRegistry()
