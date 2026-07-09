from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Literal
from uuid import uuid4

from pydantic import BaseModel, Field

from ..schemas.learning import KTDiagnosis, KTLearningProgress, LearningEvent


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
    asset_selection: dict[str, list[dict[str, Any]]] = Field(
        default_factory=lambda: {"selected": [], "omitted": []}
    )
    evidence_gaps: list[dict[str, Any]] = Field(default_factory=list)
    evidence_refs: list[str] = Field(default_factory=list)
    budget_used: int = 0
    budget_limit: int = 0
    compression_summary: dict[str, Any] = Field(default_factory=dict)
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
        source_types: list[str] | None = None,
        concept_id: str | None = None,
        question_id: str | None = None,
        freshness: list[Freshness] | None = None,
        min_confidence: float | None = None,
        intent: str | None = None,
        limit: int = 10,
    ) -> list[ContextAsset]:
        allowed_types = set(asset_types or [])
        allowed_sources = set(source_types or [])
        allowed_freshness = set(freshness or [])
        results = [
            asset
            for asset in self._assets
            if (student_id is None or asset.student_id == student_id)
            and (session_id is None or asset.session_id == session_id)
            and (not allowed_types or asset.asset_type in allowed_types)
            and (not allowed_sources or asset.source_type in allowed_sources)
            and (concept_id is None or asset.concept_id in (None, concept_id))
            and (question_id is None or asset.question_id in (None, question_id))
            and (not allowed_freshness or asset.freshness in allowed_freshness)
            and (min_confidence is None or asset.confidence >= min_confidence)
        ]
        results.sort(
            key=lambda asset: self._sort_key(
                asset,
                intent=intent,
                session_id=session_id,
                concept_id=concept_id,
                question_id=question_id,
            )
        )
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

    def _sort_key(
        self,
        asset: ContextAsset,
        *,
        intent: str | None = None,
        session_id: str | None = None,
        concept_id: str | None = None,
        question_id: str | None = None,
    ) -> tuple[int, int, int, int, float, float, str]:
        type_rank = _asset_priority(asset.asset_type, intent=intent)
        session_rank = 0 if session_id is not None and asset.session_id == session_id else 1
        target_rank = _target_match_rank(asset, concept_id=concept_id, question_id=question_id)
        freshness_rank = {"fresh": 0, "recent": 1, "stale": 2}[asset.freshness]
        return (
            target_rank,
            session_rank,
            type_rank,
            freshness_rank,
            -asset.confidence,
            _newest_first_sort_value(asset.updated_at),
            asset.asset_id,
        )


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
            memory_freshness = memory.get("freshness")
            provider_metadata = _memory_provider_metadata(memory)
            assets.append(
                ContextAsset(
                    asset_type="student_memory",
                    source_type=_memory_source_type(provider_metadata),
                    source_ref=f"memory:{memory.get('memory_id', 'unknown')}",
                    summary=str(memory.get("content", ""))[:160] or "学生长期记忆摘要",
                    content_preview=str(memory.get("content", ""))[:240],
                    metadata={
                        "memory_type": memory_type,
                        "normalized_kind": _memory_kind(memory_type),
                        "evidence": memory.get("evidence", {}),
                        "provenance": memory.get("provenance", {}),
                        "source": memory.get("source"),
                        "relevance_score": memory.get("relevance_score"),
                        "provider": provider_metadata,
                        "provider_backed": provider_metadata["provider_backed"],
                        "provider_name": provider_metadata.get("provider_name"),
                        "provider_mode": provider_metadata.get("provider_mode"),
                    },
                    evidence_refs=[f"memory:{memory.get('memory_id', 'unknown')}"],
                    confidence=_confidence_from_memory(memory),
                    freshness=(
                        memory_freshness
                        if memory_freshness in {"fresh", "recent", "stale"}
                        else "recent"
                    ),
                    student_id=student_id,
                    session_id=session_id,
                    concept_id=_concept_id_from(memory.get("evidence", {})),
                    question_id=_question_id_from(memory.get("evidence", {})),
                    included_reason=_memory_included_reason(memory_type),
                )
            )

        for item in rag_context:
            doc_type = str(item.get("doc_type") or "knowledge_resource")
            provider_metadata = _rag_provider_metadata(item)
            assets.append(
                ContextAsset(
                    asset_type="knowledge_resource",
                    source_type=_rag_source_type(provider_metadata),
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
                        "provider": provider_metadata,
                        "provider_backed": provider_metadata["provider_backed"],
                        "provider_name": provider_metadata.get("provider_name"),
                        "provider_mode": provider_metadata.get("provider_mode"),
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

    def collect_answer_submission_assets(
        self,
        *,
        student_id: str,
        session_id: str,
        learning_event: LearningEvent,
        kt_progress: KTLearningProgress,
        kt_diagnosis: KTDiagnosis | None,
        rag_context: list[dict[str, Any]],
        teaching_plan: dict[str, Any] | None,
        recommended_questions: list[dict[str, Any]],
        trace_id: str,
    ) -> list[ContextAsset]:
        if learning_event.type != "answer_submitted":
            return []

        generated_at = datetime.now(UTC).isoformat()
        question_id = (
            str(learning_event.payload["question_id"])
            if learning_event.payload.get("question_id")
            else None
        )
        concept_id = (
            str(learning_event.payload["concept_id"])
            if learning_event.payload.get("concept_id")
            else None
        )
        next_action = teaching_plan.get("selected_action") if teaching_plan else None
        mistake_diagnosis = teaching_plan.get("mistake_diagnosis") if teaching_plan else None

        assets = [
            ContextAsset(
                asset_type="task_state",
                source_type="learning_loop_event",
                source_ref=f"event:{trace_id}:answer_submitted",
                summary=(
                    f"answer_submitted question={question_id}; "
                    f"is_correct={learning_event.payload.get('is_correct')}"
                ),
                metadata={
                    "snapshot": True,
                    "state_reference_only": True,
                    "progress_ref": f"progress:{student_id}:v{kt_progress.version}",
                    "event_ref": f"event:{trace_id}:answer_submitted",
                    "trace_id": trace_id,
                    "pending_question": kt_progress.pending_question,
                    "submitted_answer": learning_event.payload.get("answer"),
                    "grading_result": {
                        "is_correct": learning_event.payload.get("is_correct"),
                        "correct_answer_available": "correct_answer" in learning_event.payload,
                        "grading_source": learning_event.payload.get("grading_source"),
                    },
                    "next_action": next_action,
                },
                evidence_refs=[
                    f"progress:{student_id}:v{kt_progress.version}",
                    f"event:{trace_id}:answer_submitted",
                    f"trace:{trace_id}",
                ],
                confidence=1.0,
                freshness="fresh",
                student_id=student_id,
                session_id=session_id,
                concept_id=concept_id,
                question_id=question_id,
                included_reason=(
                    "记录答题 task_state 快照；权威 runtime state 仍在 progress/event/trace"
                ),
            ),
            ContextAsset(
                asset_type="tool_observation",
                source_type="kt",
                source_ref=f"kt:{trace_id}:diagnosis",
                summary=(
                    "KT diagnosis snapshot: "
                    f"{len(kt_diagnosis.weak_concepts if kt_diagnosis else [])} weak concepts, "
                    f"prediction={kt_diagnosis.prediction_probability if kt_diagnosis else None}"
                ),
                metadata={
                    "snapshot": True,
                    "source": "kt",
                    "trace_id": trace_id,
                    "generated_at": generated_at,
                    "weak_concepts": kt_diagnosis.weak_concepts if kt_diagnosis else [],
                    "forgetting_risks": kt_diagnosis.forgetting_risks if kt_diagnosis else [],
                    "prediction_probability": (
                        kt_diagnosis.prediction_probability if kt_diagnosis else None
                    ),
                    "evidence": kt_diagnosis.evidence if kt_diagnosis else [],
                    "metadata": kt_diagnosis.metadata if kt_diagnosis else {},
                    "authoritative_snapshot": True,
                },
                evidence_refs=[f"kt-diagnosis:{trace_id}", f"trace:{trace_id}"],
                confidence=1.0,
                freshness="fresh",
                student_id=student_id,
                session_id=session_id,
                concept_id=concept_id,
                question_id=question_id,
                included_reason="记录 KT 工具观察快照；不能覆盖当前 KT facts",
            ),
            ContextAsset(
                asset_type="tool_observation",
                source_type="rag",
                source_ref=f"rag:{trace_id}:retrieval",
                summary=f"RAG retrieval snapshot: {len(rag_context)} sources",
                metadata={
                    "snapshot": True,
                    "source": "rag",
                    "trace_id": trace_id,
                    "generated_at": generated_at,
                    "source_count": len(rag_context),
                    "sources": [
                        {
                            "doc_id": item.get("doc_id"),
                            "doc_type": item.get("doc_type"),
                            "source": item.get("source"),
                            "concept_id": item.get("concept_id"),
                            "question_id": item.get("question_id"),
                        }
                        for item in rag_context
                    ],
                },
                evidence_refs=[
                    str(item.get("source") or item.get("doc_id"))
                    for item in rag_context
                    if item.get("source") or item.get("doc_id")
                ]
                or [f"trace:{trace_id}"],
                confidence=0.8 if rag_context else 0.4,
                freshness="fresh",
                student_id=student_id,
                session_id=session_id,
                concept_id=concept_id,
                question_id=question_id,
                included_reason=(
                    "记录 RAG 检索工具观察快照"
                    if rag_context
                    else None
                ),
                excluded_reason=(
                    None
                    if rag_context
                    else "本轮没有 RAG 检索结果，未生成 knowledge evidence"
                ),
            ),
            ContextAsset(
                asset_type="tool_observation",
                source_type="mistake_diagnoser",
                source_ref=f"mistake:{trace_id}:diagnosis",
                summary=(
                    f"mistake diagnosis snapshot for {question_id}"
                    if mistake_diagnosis
                    else "mistake diagnosis omitted"
                ),
                metadata={
                    "snapshot": True,
                    "source": "mistake_diagnoser",
                    "trace_id": trace_id,
                    "generated_at": generated_at,
                    "mistake_diagnosis": mistake_diagnosis,
                },
                evidence_refs=[f"trace:{trace_id}"],
                confidence=0.85 if mistake_diagnosis else 0.5,
                freshness="fresh",
                student_id=student_id,
                session_id=session_id,
                concept_id=concept_id,
                question_id=question_id,
                included_reason=(
                    "记录错因诊断工具观察快照"
                    if mistake_diagnosis
                    else None
                ),
                excluded_reason=(
                    None
                    if mistake_diagnosis
                    else "正确作答或未判题，本轮没有错因诊断"
                ),
            ),
            ContextAsset(
                asset_type="tool_observation",
                source_type="recommender",
                source_ref=f"recommender:{trace_id}:candidates",
                summary=f"recommendation candidates snapshot: {len(recommended_questions)} selected",
                metadata={
                    "snapshot": True,
                    "source": "recommender",
                    "trace_id": trace_id,
                    "generated_at": generated_at,
                    "selected_question_ids": [
                        question.get("question_id") for question in recommended_questions
                    ],
                    "candidates": [
                        {
                            "question_id": question.get("question_id"),
                            "concept_id": question.get("concept_id"),
                            "score": question.get("score"),
                            "reason": question.get("reason"),
                        }
                        for question in recommended_questions
                    ],
                },
                evidence_refs=[
                    f"question:{question.get('question_id')}"
                    for question in recommended_questions
                    if question.get("question_id")
                ]
                or [f"trace:{trace_id}"],
                confidence=0.85,
                freshness="fresh",
                student_id=student_id,
                session_id=session_id,
                concept_id=concept_id,
                question_id=question_id,
                included_reason="记录推荐器候选快照",
            ),
            ContextAsset(
                asset_type="trace_reference",
                source_type="teaching_trace",
                source_ref=f"trace:{trace_id}:answer_submission",
                summary="answer_submitted trace references retrieval, decision, and memory-update source",
                metadata={
                    "snapshot": True,
                    "trace_id": trace_id,
                    "retrieval_refs": [
                        str(item.get("source") or item.get("doc_id"))
                        for item in rag_context
                        if item.get("source") or item.get("doc_id")
                    ],
                    "decision_ref": f"planner:{trace_id}",
                    "memory_update_source": f"event:{trace_id}:answer_submitted",
                    "selected_action": next_action,
                    "state_reference_only": True,
                },
                evidence_refs=[f"trace:{trace_id}", f"planner:{trace_id}"],
                confidence=1.0,
                freshness="fresh",
                student_id=student_id,
                session_id=session_id,
                concept_id=concept_id,
                question_id=question_id,
                included_reason="记录 trace 引用，串联检索路径、决策证据和 memory update 来源",
            ),
        ]

        return self.store.write_many(assets)

    def retrieve_assets(
        self,
        *,
        student_id: str,
        session_id: str | None = None,
        asset_types: list[ContextAssetType] | None = None,
        source_types: list[str] | None = None,
        concept_id: str | None = None,
        question_id: str | None = None,
        freshness: list[Freshness] | None = None,
        min_confidence: float | None = None,
        intent: str | None = None,
        top_k: int = 8,
    ) -> list[ContextAsset]:
        session_assets = self.store.search(
            student_id=student_id,
            session_id=session_id,
            asset_types=asset_types,
            source_types=source_types,
            concept_id=concept_id,
            question_id=question_id,
            freshness=freshness,
            min_confidence=min_confidence,
            intent=intent,
            limit=top_k,
        )
        if session_id is None or len(session_assets) >= top_k:
            return session_assets
        broader_assets = self.store.search(
            student_id=student_id,
            asset_types=asset_types,
            source_types=source_types,
            concept_id=concept_id,
            question_id=question_id,
            freshness=freshness,
            min_confidence=min_confidence,
            intent=intent,
            limit=top_k,
        )
        combined = {asset.asset_id: asset for asset in [*session_assets, *broader_assets]}
        return sorted(
            combined.values(),
            key=lambda asset: self.store._sort_key(
                asset,
                intent=intent,
                session_id=session_id,
                concept_id=concept_id,
                question_id=question_id,
            ),
        )[:top_k]

    def assemble_context(
        self,
        *,
        intent: str,
        assets: list[ContextAsset],
        kt_facts: dict[str, Any],
        token_budget: int = 1200,
    ) -> AssembledContext:
        ranked_assets = sorted(
            assets,
            key=lambda asset: self.store._sort_key(asset, intent=intent),
        )
        selected_assets, excluded_summaries, budget_used = self._select_assets_for_budget(
            ranked_assets,
            token_budget=token_budget,
        )
        asset_summaries = [
            self._asset_summary(
                asset,
                selection_status="included",
                budget_cost=self._asset_budget_cost(asset),
                included_reason=asset.included_reason
                or _default_included_reason(asset.asset_type),
            )
            for asset in selected_assets
        ] + excluded_summaries
        asset_selection = _asset_selection_from_summaries(asset_summaries)
        normalized_context = self._normalize_assets(selected_assets)
        evidence_gaps = self._evidence_gaps(
            normalized_context,
            candidate_assets=ranked_assets,
            selected_assets=selected_assets,
            excluded_summaries=excluded_summaries,
        )
        compression_summary = {
            "strategy": "priority_budget_summary",
            "budget_used": budget_used,
            "budget_limit": token_budget,
            "candidate_asset_count": len(ranked_assets),
            "selected_asset_count": len(selected_assets),
            "excluded_asset_count": len(excluded_summaries),
            "priority_order": [
                "kt_facts",
                "task_state",
                "tool_observation",
                "student_memory",
                "knowledge_resource",
                "trace_reference",
            ],
            "excluded_reasons": list(
                dict.fromkeys(
                    str(summary["excluded_reason"])
                    for summary in excluded_summaries
                    if summary.get("excluded_reason")
                )
            ),
        }
        return AssembledContext(
            intent=intent,
            authoritative_kt_facts=dict(kt_facts),
            normalized_context=normalized_context,
            asset_summaries=asset_summaries,
            asset_selection=asset_selection,
            evidence_gaps=evidence_gaps,
            evidence_refs=list(
                dict.fromkeys(
                    ref for asset in selected_assets for ref in asset.evidence_refs if ref
                )
            ),
            budget_used=budget_used,
            budget_limit=token_budget,
            compression_summary=compression_summary,
            budget={
                "token_budget": token_budget,
                "budget_limit": token_budget,
                "budget_used": budget_used,
                "selected_asset_count": len(selected_assets),
                "candidate_asset_count": len(assets),
                "excluded_asset_count": len(excluded_summaries),
            },
            compression=compression_summary | {"full_payload_copied": False},
        )

    def _select_assets_for_budget(
        self,
        assets: list[ContextAsset],
        *,
        token_budget: int,
    ) -> tuple[list[ContextAsset], list[dict[str, Any]], int]:
        selected: list[ContextAsset] = []
        excluded: list[dict[str, Any]] = []
        budget_used = 0
        for asset in assets:
            cost = self._asset_budget_cost(asset)
            if asset.excluded_reason:
                excluded.append(
                    self._asset_summary(
                        asset,
                        selection_status="excluded",
                        budget_cost=cost,
                        excluded_reason=asset.excluded_reason,
                    )
                )
                continue
            if budget_used + cost > token_budget:
                excluded.append(
                    self._asset_summary(
                        asset,
                        selection_status="excluded",
                        budget_cost=cost,
                        excluded_reason="超出上下文预算，已裁剪低优先级资产",
                    )
                )
                continue
            selected.append(asset)
            budget_used += cost
        return selected, excluded, budget_used

    def _asset_budget_cost(self, asset: ContextAsset) -> int:
        preview = asset.content_preview or ""
        metadata_hint = " ".join(str(ref) for ref in asset.evidence_refs[:3])
        raw_size = len(asset.summary) + len(preview) + len(metadata_hint)
        return max(1, (raw_size + 15) // 16)

    def _asset_summary(
        self,
        asset: ContextAsset,
        *,
        selection_status: str,
        budget_cost: int,
        included_reason: str | None = None,
        excluded_reason: str | None = None,
    ) -> dict[str, Any]:
        return {
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
            "included_reason": included_reason if selection_status == "included" else None,
            "excluded_reason": excluded_reason,
            "selection_status": selection_status,
            "budget_cost": budget_cost,
            "evidence_refs": asset.evidence_refs,
        }

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

    def _evidence_gaps(
        self,
        normalized_context: dict[str, Any],
        *,
        candidate_assets: list[ContextAsset] | None = None,
        selected_assets: list[ContextAsset] | None = None,
        excluded_summaries: list[dict[str, Any]] | None = None,
    ) -> list[dict[str, Any]]:
        gaps: list[dict[str, Any]] = []
        candidate_assets = candidate_assets or []
        selected_assets = selected_assets or []
        excluded_summaries = excluded_summaries or []
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
        selected_task_assets = [
            asset for asset in selected_assets if asset.asset_type == "task_state"
        ]
        if selected_task_assets and all(
            asset.freshness == "stale" for asset in selected_task_assets
        ):
            gaps.append(
                {
                    "gap_type": "stale_task_state",
                    "reason": "task_state 上下文已过期",
                    "impact": "planner should prefer current event/progress state",
                }
            )
        low_confidence_observations = [
            asset
            for asset in candidate_assets
            if asset.asset_type == "tool_observation" and asset.confidence < 0.5
        ]
        if low_confidence_observations:
            gaps.append(
                {
                    "gap_type": "low_confidence_observation",
                    "reason": "存在低置信度 tool_observation",
                    "impact": "low confidence observations are evidence only, not KT facts",
                    "asset_ids": [
                        asset.asset_id for asset in low_confidence_observations[:5]
                    ],
                }
            )
        provider_failures = [
            asset
            for asset in candidate_assets
            if asset.metadata.get("provider_error")
            or asset.metadata.get("provider_failure")
            or asset.source_type.endswith("_failure")
        ]
        if provider_failures:
            gaps.append(
                {
                    "gap_type": "provider_failure",
                    "reason": "上下文 provider 返回失败记录",
                    "impact": "local fallback continues without fabricating provider evidence",
                    "asset_ids": [asset.asset_id for asset in provider_failures[:5]],
                }
            )
        if any(
            summary.get("excluded_reason") == "超出上下文预算，已裁剪低优先级资产"
            for summary in excluded_summaries
        ):
            gaps.append(
                {
                    "gap_type": "context_budget",
                    "reason": "部分上下文资产因预算限制被裁剪",
                    "impact": "lower priority context remains visible in asset_summaries",
                }
            )
        return gaps


def _asset_priority(asset_type: ContextAssetType, *, intent: str | None = None) -> int:
    priority = {
        "task_state": 0,
        "tool_observation": 1,
        "student_memory": 2,
        "knowledge_resource": 3,
        "trace_reference": 4,
    }
    if intent == "next_step_advice":
        priority["student_memory"] = 1
        priority["tool_observation"] = 2
    return priority[asset_type]


def _target_match_rank(
    asset: ContextAsset,
    *,
    concept_id: str | None = None,
    question_id: str | None = None,
) -> int:
    if question_id is not None and asset.question_id == question_id:
        return 0
    if concept_id is not None and asset.concept_id == concept_id:
        return 1
    if asset.question_id is None and asset.concept_id is None:
        return 2
    return 3


def _default_included_reason(asset_type: ContextAssetType) -> str:
    reasons = {
        "task_state": "纳入当前任务状态快照",
        "tool_observation": "纳入工具观察快照",
        "student_memory": "纳入学生记忆上下文",
        "knowledge_resource": "纳入知识资源上下文",
        "trace_reference": "纳入 trace 引用路径",
    }
    return reasons[asset_type]


def _newest_first_sort_value(value: str) -> float:
    try:
        return -datetime.fromisoformat(value).timestamp()
    except ValueError:
        return 0.0


def _concept_id_from(value: Any) -> str | None:
    if isinstance(value, dict) and value.get("concept_id"):
        return str(value["concept_id"])
    return None


def _question_id_from(value: Any) -> str | None:
    if isinstance(value, dict) and value.get("question_id"):
        return str(value["question_id"])
    return None


def _confidence_from_memory(memory: dict[str, Any]) -> float:
    score = memory.get("relevance_score")
    if score is None:
        return 0.75
    try:
        return round(min(max(float(score), 0.0), 1.0), 4)
    except (TypeError, ValueError):
        return 0.75


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


def _memory_provider_metadata(memory: dict[str, Any]) -> dict[str, Any]:
    source = str(memory.get("source") or "")
    provenance = memory.get("provenance") if isinstance(memory.get("provenance"), dict) else {}
    provider = provenance.get("provider") if isinstance(provenance, dict) else None
    provider_name = provider.get("name") if isinstance(provider, dict) else None
    provider_record_id = provider.get("record_id") if isinstance(provider, dict) else None
    provider_mode = None
    if source == "fake_provider":
        provider_mode = "fake_provider"
    elif source in {"mem0", "mem0_unavailable"}:
        provider_mode = "live_provider"
    elif source == "local_fallback":
        provider_mode = "local_fallback"
    provider_backed = bool(provider_name or provider_mode in {"fake_provider", "live_provider"})
    return {
        "provider_backed": provider_backed,
        "provider_name": provider_name,
        "provider_mode": provider_mode,
        "provider_record_id": provider_record_id,
        "source": source,
    }


def _rag_provider_metadata(item: dict[str, Any]) -> dict[str, Any]:
    provenance = item.get("provenance") if isinstance(item.get("provenance"), dict) else {}
    provider_name = provenance.get("provider_name") if isinstance(provenance, dict) else None
    provider_mode = provenance.get("provider_mode") if isinstance(provenance, dict) else None
    provider_record_id = provenance.get("provider_record_id") if isinstance(provenance, dict) else None
    provider_backed = bool(provider_name or provider_mode in {"fake_provider", "live_provider"})
    return {
        "provider_backed": provider_backed,
        "provider_name": provider_name,
        "provider_mode": provider_mode,
        "provider_record_id": provider_record_id,
        "source": item.get("source"),
    }


def _memory_source_type(provider_metadata: dict[str, Any]) -> str:
    if provider_metadata.get("provider_backed"):
        return "provider_memory"
    return "student_memory_store"


def _rag_source_type(provider_metadata: dict[str, Any]) -> str:
    if provider_metadata.get("provider_backed"):
        return "provider_rag"
    return "local_rag"


def _asset_selection_from_summaries(
    summaries: list[dict[str, Any]],
) -> dict[str, list[dict[str, Any]]]:
    selected: list[dict[str, Any]] = []
    omitted: list[dict[str, Any]] = []
    for summary in summaries:
        if summary.get("selection_status") == "excluded":
            omitted.append(summary)
        else:
            selected.append(summary)
    return {"selected": selected, "omitted": omitted}


context_layer = LearningContextLayer()
