from __future__ import annotations

from typing import Any
from uuid import uuid4

from pydantic import BaseModel, Field


class ContextGovernanceOverview(BaseModel):
    """Read-only audit summary for one mathematics learning turn."""

    governance_id: str = Field(default_factory=lambda: f"governance-{uuid4().hex[:12]}")
    intent: str
    budget_summary: dict[str, Any] = Field(default_factory=dict)
    evidence_priority_rules: list[str] = Field(default_factory=list)
    evidence_selection_summary: dict[str, Any] = Field(default_factory=dict)
    evidence_decisions: list[dict[str, Any]] = Field(default_factory=list)
    non_clippable_evidence: list[str] = Field(default_factory=list)
    tool_mount_summary: dict[str, Any] = Field(default_factory=dict)
    response_context_ref: str | None = None
    state_reference_only: bool = True
    boundary: str = (
        "Runtime Context Governance only orchestrates and audits context; it cannot "
        "overwrite KT/DGEKT facts, learning progress, RAG, memory, or LearningContextLayer."
    )


class ResponseContextPackage(BaseModel):
    """The only structured context contract intended for a future response/LLM layer."""

    context_package_id: str = Field(default_factory=lambda: f"response-context-{uuid4().hex[:12]}")
    governance_id: str
    intent: str
    authority_boundary: dict[str, str]
    authoritative_kt_facts: dict[str, Any] = Field(default_factory=dict)
    task_state: list[dict[str, Any]] = Field(default_factory=list)
    rag_evidence: list[dict[str, Any]] = Field(default_factory=list)
    student_memory: list[dict[str, Any]] = Field(default_factory=list)
    evidence_refs: list[str] = Field(default_factory=list)
    selected_evidence_only: bool = True
    debug_evidence_included: bool = False
    state_reference_only: bool = True
