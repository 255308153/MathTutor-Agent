from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Literal
from uuid import uuid4

from pydantic import BaseModel, Field

from ..schemas.learning import KTLearningProgress, LearningEvent


ContextAssetType = Literal[
    "student_memory",
    "knowledge_resource",
    "task_state",
    "tool_observation",
    "trace_reference",
]
Freshness = Literal["fresh", "recent", "stale"]


class ContextAsset(BaseModel):
    asset_id: str = Field(default_factory=lambda: f"ctx-{uuid4().hex[:12]}")
    asset_type: ContextAssetType
    source_type: str = Field(min_length=1)
    source_ref: str = Field(min_length=1)
    summary: str = Field(min_length=1)
    content_preview: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    evidence_refs: list[str] = Field(default_factory=list)
    confidence: float = Field(default=0.7, ge=0.0, le=1.0)
    freshness: Freshness = "fresh"
    student_id: str | None = None
    session_id: str | None = None
    concept_id: str | None = None
    question_id: str | None = None
    included_reason: str | None = None
    excluded_reason: str | None = None
    created_at: str = Field(default_factory=lambda: datetime.now(UTC).isoformat())
    updated_at: str = Field(default_factory=lambda: datetime.now(UTC).isoformat())
    expires_at: str | None = None


class AssembledContext(BaseModel):
    context_id: str = Field(default_factory=lambda: f"assembled-{uuid4().hex[:12]}")
    intent: str
    authoritative_kt_facts: dict[str, Any] = Field(default_factory=dict)
    normalized_context: dict[str, Any] = Field(default_factory=dict)
    asset_summaries: list[dict[str, Any]] = Field(default_factory=list)
    evidence_gaps: list[dict[str, Any]] = Field(default_factory=list)
    evidence_refs: list[str] = Field(default_factory=list)
    budget: dict[str, Any] = Field(default_factory=dict)
    compression: dict[str, Any] = Field(default_factory=dict)
    context_invariants: dict[str, str] = Field(
        default_factory=lambda: {
            "kt_boundary": "KT facts are authoritative.",
            "memory_boundary": "Memory can influence strategy, not mastery.",
            "rag_boundary": "RAG can support explanation, not overwrite prediction facts.",
            "context_boundary": "Context can assemble evidence, not decide learning facts.",
        }
    )
    created_at: str = Field(default_factory=lambda: datetime.now(UTC).isoformat())


class ContextAssemblyRecord(BaseModel):
    record_id: str = Field(default_factory=lambda: f"ctx-record-{uuid4().hex[:12]}")
    session_id: str
    student_id: str
    context_id: str
    asset_ids: list[str] = Field(default_factory=list)
    summary: str = ""
    created_at: str = Field(default_factory=lambda: datetime.now(UTC).isoformat())


class InMemoryContextAssetStore:
    """Local fallback store for context references and assembly records.

    This deliberately stores summaries, references and trace records; runtime state remains
    owned by the learning loop, progress store, KT engine, RAG and memory stores.
    """

    def __init__(self) -> None:
        self._assets: list[ContextAsset] = []
        self._assembly_records: list[ContextAssemblyRecord] = []

    def write(self, asset: ContextAsset) -> ContextAsset:
        now = datetime.now(UTC).isoformat()
        updated = asset.model_copy(update={"updated_at": now})
        for index, existing in enumerate(self._assets):
            if existing.asset_id == updated.asset_id:
                self._assets[index] = updated
                return updated
        self._assets.append(updated)
        return updated

    def write_many(self, assets: list[ContextAsset]) -> list[ContextAsset]:
        return [self.write(asset) for asset in assets]

    def search(
        self,
        *,
        student_id: str | None = None,
        session_id: str | None = None,
        asset_types: list[ContextAssetType] | None = None,
        concept_id: str | None = None,
        question_id: str | None = None,
        limit: int = 10,
    ) -> list[ContextAsset]:
        allowed_types = set(asset_types or [])
        results = [
            asset
            for asset in self._assets
            if (student_id is None or asset.student_id == student_id)
            and (session_id is None or asset.session_id == session_id)
            and (not allowed_types or asset.asset_type in allowed_types)
            and (concept_id is None or asset.concept_id in (None, concept_id))
            and (question_id is None or asset.question_id in (None, question_id))
        ]
        results.sort(key=self._sort_key)
        return results[:limit]

    def record_assembly(
        self,
        *,
        session_id: str,
        student_id: str,
        assembled_context: AssembledContext,
    ) -> ContextAssemblyRecord:
        record = ContextAssemblyRecord(
            session_id=session_id,
            student_id=student_id,
            context_id=assembled_context.context_id,
            asset_ids=[
                str(summary["asset_id"])
                for summary in assembled_context.asset_summaries
                if summary.get("asset_id")
            ],
            summary=f"assembled {len(assembled_context.asset_summaries)} context assets",
        )
        self._assembly_records.append(record)
        return record

    def list_assembly_records(
        self,
        *,
        student_id: str | None = None,
        session_id: str | None = None,
        limit: int = 10,
    ) -> list[ContextAssemblyRecord]:
        records = [
            record
            for record in self._assembly_records
            if (student_id is None or record.student_id == student_id)
            and (session_id is None or record.session_id == session_id)
        ]
        return sorted(records, key=lambda record: (record.created_at, record.record_id), reverse=True)[
            :limit
        ]

    def _sort_key(self, asset: ContextAsset) -> tuple[int, float, str, str]:
        freshness_rank = {"fresh": 0, "recent": 1, "stale": 2}[asset.freshness]
        return (freshness_rank, -asset.confidence, asset.created_at, asset.asset_id)


class LearningContextLayer:
    def __init__(self, store: InMemoryContextAssetStore | None = None) -> None:
        self.store = store or InMemoryContextAssetStore()

    def collect_assets(
        self,
        *,
        student_id: str,
        session_id: str,
        intent: str,
        learning_event: LearningEvent,
        kt_progress: KTLearningProgress,
        student_memories: list[dict[str, Any]],
        rag_context: list[dict[str, Any]],
        kt_facts: dict[str, Any],
        trace_id: str,
    ) -> list[ContextAsset]:
        assets: list[ContextAsset] = []
        for memory in student_memories:
            memory_type = str(memory.get("memory_type") or "reflection")
            assets.append(
                ContextAsset(
                    asset_type="student_memory",
                    source_type="student_memory_store",
                    source_ref=f"memory:{memory.get('memory_id', 'unknown')}",
                    summary=str(memory.get("content", ""))[:160] or "学生长期记忆摘要",
                    content_preview=str(memory.get("content", ""))[:240],
                    metadata={
                        "memory_type": memory_type,
                        "normalized_kind": _memory_kind(memory_type),
                        "evidence": memory.get("evidence", {}),
                    },
                    evidence_refs=[f"memory:{memory.get('memory_id', 'unknown')}"],
                    confidence=0.75,
                    freshness="recent",
                    student_id=student_id,
                    session_id=session_id,
                    concept_id=_concept_id_from(memory.get("evidence", {})),
                    question_id=_question_id_from(memory.get("evidence", {})),
                    included_reason=_memory_included_reason(memory_type),
                )
            )

        for item in rag_context:
            doc_type = str(item.get("doc_type") or "knowledge_resource")
            assets.append(
                ContextAsset(
                    asset_type="knowledge_resource",
                    source_type="local_rag",
                    source_ref=f"rag:{item.get('doc_id', 'unknown')}",
                    summary=str(item.get("title") or item.get("content") or "RAG evidence")[:160],
                    content_preview=str(item.get("content", ""))[:240],
                    metadata={
                        "doc_type": doc_type,
                        "normalized_kind": _knowledge_kind(doc_type),
                        "score": item.get("score"),
                        "source": item.get("source"),
                        "assist2017_question_id": item.get("assist2017_question_id"),
                        "assist2017_concept_id": item.get("assist2017_concept_id"),
                        "canonical_mapping": item.get("canonical_mapping", {}),
                        "provenance": item.get("provenance", {}),
                        "coverage": item.get("coverage", {}),
                    },
                    evidence_refs=[str(item.get("source") or item.get("doc_id", ""))],
                    confidence=min(float(item.get("score") or 0.6), 1.0),
                    freshness="fresh",
                    student_id=student_id,
                    session_id=session_id,
                    concept_id=item.get("concept_id"),
                    question_id=item.get("question_id"),
                    included_reason=_knowledge_included_reason(doc_type),
                )
            )

        assets.append(
            ContextAsset(
                asset_type="task_state",
                source_type="learning_loop_state",
                source_ref=f"progress:{student_id}:v{kt_progress.version}",
                summary=f"intent={intent}; event={learning_event.type}; progress_version={kt_progress.version}",
                metadata={
                    "intent": intent,
                    "event_type": learning_event.type,
                    "pending_question_id": (
                        kt_progress.pending_question or {}
                    ).get("question_id"),
                    "recent_event_count": len(kt_progress.recent_events),
                    "state_reference_only": True,
                },
                evidence_refs=[f"trace:{trace_id}"],
                confidence=1.0,
                freshness="fresh",
                student_id=student_id,
                session_id=session_id,
                concept_id=str(learning_event.payload.get("concept_id"))
                if learning_event.payload.get("concept_id")
                else None,
                question_id=str(learning_event.payload.get("question_id"))
                if learning_event.payload.get("question_id")
                else None,
                included_reason="task_state is a snapshot reference, not authoritative runtime state",
            )
        )

        assets.append(
            ContextAsset(
                asset_type="tool_observation",
                source_type="kt_engine",
                source_ref=f"kt:{trace_id}",
                summary=(
                    f"KT diagnosis: {len(kt_facts.get('weak_concepts', []))} weak concepts, "
                    f"{len(kt_facts.get('forgetting_risks', []))} forgetting risks"
                ),
                metadata={
                    "snapshot": True,
                    "weak_concept_count": len(kt_facts.get("weak_concepts", [])),
                    "forgetting_risk_count": len(kt_facts.get("forgetting_risks", [])),
                    "prediction_probability": kt_facts.get("prediction_probability"),
                },
                evidence_refs=[f"kt-diagnosis:{trace_id}"],
                confidence=1.0,
                freshness="fresh",
                student_id=student_id,
                session_id=session_id,
                included_reason="KT observation is recorded as evidence; KT facts remain authoritative",
            )
        )

        assets.append(
            ContextAsset(
                asset_type="trace_reference",
                source_type="teaching_trace",
                source_ref=f"trace:{trace_id}",
                summary="Context assembly references this TeachingTrace run.",
                metadata={"trace_id": trace_id, "intent": intent},
                evidence_refs=[f"trace:{trace_id}"],
                confidence=1.0,
                freshness="fresh",
                student_id=student_id,
                session_id=session_id,
                included_reason="trace reference links context choices back to the current run",
            )
        )

        return self.store.write_many(assets)

    def retrieve_assets(
        self,
        *,
        student_id: str,
        session_id: str | None = None,
        asset_types: list[ContextAssetType] | None = None,
        concept_id: str | None = None,
        question_id: str | None = None,
        top_k: int = 8,
    ) -> list[ContextAsset]:
        session_assets = self.store.search(
            student_id=student_id,
            session_id=session_id,
            asset_types=asset_types,
            concept_id=concept_id,
            question_id=question_id,
            limit=top_k,
        )
        if session_id is None or len(session_assets) >= top_k:
            return session_assets
        broader_assets = self.store.search(
            student_id=student_id,
            asset_types=asset_types,
            concept_id=concept_id,
            question_id=question_id,
            limit=top_k,
        )
        combined = {asset.asset_id: asset for asset in [*session_assets, *broader_assets]}
        return sorted(combined.values(), key=self.store._sort_key)[:top_k]

    def assemble_context(
        self,
        *,
        intent: str,
        assets: list[ContextAsset],
        kt_facts: dict[str, Any],
        token_budget: int = 1200,
    ) -> AssembledContext:
        selected_assets = assets[:8]
        asset_summaries = [
            {
                "asset_id": asset.asset_id,
                "asset_type": asset.asset_type,
                "source_type": asset.source_type,
                "source_ref": asset.source_ref,
                "summary": asset.summary,
                "content_preview": asset.content_preview,
                "metadata": asset.metadata,
                "concept_id": asset.concept_id,
                "question_id": asset.question_id,
                "confidence": asset.confidence,
                "freshness": asset.freshness,
                "included_reason": asset.included_reason,
                "excluded_reason": asset.excluded_reason,
                "evidence_refs": asset.evidence_refs,
            }
            for asset in selected_assets
        ]
        normalized_context = self._normalize_assets(selected_assets)
        evidence_gaps = self._evidence_gaps(normalized_context)
        return AssembledContext(
            intent=intent,
            authoritative_kt_facts=dict(kt_facts),
            normalized_context=normalized_context,
            asset_summaries=asset_summaries,
            evidence_gaps=evidence_gaps,
            evidence_refs=list(
                dict.fromkeys(ref for asset in selected_assets for ref in asset.evidence_refs if ref)
            ),
            budget={
                "token_budget": token_budget,
                "selected_asset_count": len(selected_assets),
                "candidate_asset_count": len(assets),
            },
            compression={
                "strategy": "summary_only_local_fallback",
                "full_payload_copied": False,
                "priority_order": [
                    "kt_facts",
                    "task_state",
                    "student_memory",
                    "knowledge_resource",
                    "trace_reference",
                ],
            },
        )

    def record_context_trace(
        self,
        *,
        session_id: str,
        student_id: str,
        assembled_context: AssembledContext,
    ) -> dict[str, Any]:
        record = self.store.record_assembly(
            session_id=session_id,
            student_id=student_id,
            assembled_context=assembled_context,
        )
        return {
            "record_id": record.record_id,
            "context_id": record.context_id,
            "asset_ids": record.asset_ids,
            "summary": record.summary,
        }

    def _normalize_assets(self, assets: list[ContextAsset]) -> dict[str, Any]:
        grouped: dict[str, Any] = {
            "student_memory": [],
            "knowledge_resource": [],
            "task_state": [],
            "tool_observation": [],
            "trace_reference": [],
        }
        for asset in assets:
            item = {
                "asset_id": asset.asset_id,
                "kind": asset.metadata.get("normalized_kind") or asset.asset_type,
                "summary": asset.summary,
                "content_preview": asset.content_preview,
                "source_type": asset.source_type,
                "source_ref": asset.source_ref,
                "concept_id": asset.concept_id,
                "question_id": asset.question_id,
                "included_reason": asset.included_reason,
                "evidence_refs": asset.evidence_refs,
                "confidence": asset.confidence,
                "freshness": asset.freshness,
                "metadata": asset.metadata,
            }
            grouped[asset.asset_type].append(item)

        return grouped | {
            "strategy_hints": self._strategy_hints(grouped["student_memory"]),
            "knowledge_hints": self._knowledge_hints(grouped["knowledge_resource"]),
        }

    def _strategy_hints(self, memories: list[dict[str, Any]]) -> dict[str, Any]:
        hints: dict[str, Any] = {
            "preferred_teaching_type": None,
            "preferred_concept_id": None,
            "repeated_mistakes": [],
            "effective_strategies": [],
            "goals": [],
            "included_reasons": [],
        }
        for memory in memories:
            metadata = memory.get("metadata", {})
            evidence = metadata.get("evidence", {}) if isinstance(metadata, dict) else {}
            if evidence.get("preferred_teaching_type") and hints["preferred_teaching_type"] is None:
                hints["preferred_teaching_type"] = evidence["preferred_teaching_type"]
            if evidence.get("preferred_concept_id") and hints["preferred_concept_id"] is None:
                hints["preferred_concept_id"] = evidence["preferred_concept_id"]
            kind = memory.get("kind")
            if kind == "repeated_mistake":
                hints["repeated_mistakes"].append(memory["summary"])
            elif kind == "effective_strategy":
                hints["effective_strategies"].append(memory["summary"])
            elif kind == "goal":
                hints["goals"].append(memory["summary"])
            if memory.get("included_reason"):
                hints["included_reasons"].append(memory["included_reason"])
        hints["included_reasons"] = list(dict.fromkeys(hints["included_reasons"]))
        return hints

    def _knowledge_hints(self, resources: list[dict[str, Any]]) -> dict[str, Any]:
        return {
            "resource_count": len(resources),
            "doc_types": list(
                dict.fromkeys(
                    str(resource.get("metadata", {}).get("doc_type"))
                    for resource in resources
                    if resource.get("metadata", {}).get("doc_type")
                )
            ),
            "sources": list(
                dict.fromkeys(
                    str(resource.get("metadata", {}).get("source"))
                    for resource in resources
                    if resource.get("metadata", {}).get("source")
                )
            ),
            "included_reasons": list(
                dict.fromkeys(
                    str(resource["included_reason"])
                    for resource in resources
                    if resource.get("included_reason")
                )
            ),
        }

    def _evidence_gaps(self, normalized_context: dict[str, Any]) -> list[dict[str, Any]]:
        gaps: list[dict[str, Any]] = []
        if not normalized_context.get("student_memory"):
            gaps.append(
                {
                    "gap_type": "student_memory",
                    "reason": "无可用记忆",
                    "impact": "recommendation uses KT facts and content only",
                }
            )
        if not normalized_context.get("knowledge_resource"):
            gaps.append(
                {
                    "gap_type": "knowledge_resource",
                    "reason": "RAG 未找到相关知识资源",
                    "impact": "no knowledge_resource asset was fabricated",
                }
            )
        return gaps


def _concept_id_from(value: Any) -> str | None:
    if isinstance(value, dict) and value.get("concept_id"):
        return str(value["concept_id"])
    return None


def _question_id_from(value: Any) -> str | None:
    if isinstance(value, dict) and value.get("question_id"):
        return str(value["question_id"])
    return None


def _memory_kind(memory_type: str) -> str:
    if memory_type in {"preference", "repeated_mistake", "effective_strategy"}:
        return memory_type
    if memory_type == "reflection":
        return "goal"
    return "student_memory"


def _knowledge_kind(doc_type: str) -> str:
    if doc_type in {"concept_note", "question_explanation", "mistake_pattern", "learning_strategy"}:
        return doc_type
    return "knowledge_resource"


def _memory_included_reason(memory_type: str) -> str:
    reasons = {
        "preference": "参考学生偏好",
        "repeated_mistake": "参考重复错因",
        "effective_strategy": "参考有效策略",
        "reflection": "参考学习目标或反思",
    }
    return reasons.get(memory_type, "参考学生记忆")


def _knowledge_included_reason(doc_type: str) -> str:
    reasons = {
        "concept_note": "参考相关知识资源",
        "question_explanation": "参考题目解析资源",
        "mistake_pattern": "参考错因模式资源",
        "learning_strategy": "参考学习策略资源",
    }
    return reasons.get(doc_type, "参考相关知识资源")


context_layer = LearningContextLayer()
