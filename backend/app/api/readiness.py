from __future__ import annotations

from fastapi import APIRouter, HTTPException

from . import events as events_api
from ..readiness.gate import build_trial_readiness_report
from ..readiness.probes import run_canary_probes
from ..schemas.readiness import (
    CanaryProbeRequest,
    SessionRecoveryResponse,
    TrialFeedbackCreate,
    TrialFeedbackRecord,
    TrialProbeSummary,
    TrialReadinessReport,
)
from ..storage.sqlite_store import get_learning_store

router = APIRouter(tags=["trial-readiness"])


@router.get("/trial-readiness", response_model=TrialReadinessReport)
def trial_readiness() -> TrialReadinessReport:
    """Read-only Trial Readiness Gate. Never writes learning facts."""
    return build_trial_readiness_report(provider_gaps=_runtime_provider_gaps())


@router.post("/trial-readiness/probes", response_model=list[TrialProbeSummary])
def trigger_canary_probes(request: CanaryProbeRequest) -> list[TrialProbeSummary]:
    """Explicit opt-in canary probes. Default settings safely skip live access."""
    return run_canary_probes(
        providers=request.providers,
        canary_token=request.canary_token,
    )


@router.post("/trial-readiness/feedback", response_model=TrialFeedbackRecord)
def record_trial_feedback(request: TrialFeedbackCreate) -> TrialFeedbackRecord:
    """Record a human trial decision. Never auto-approves from health alone."""
    return get_learning_store().save_trial_feedback(request)


@router.get(
    "/students/{student_id}/sessions/{session_id}/recovery",
    response_model=SessionRecoveryResponse,
)
def recover_student_session(student_id: str, session_id: str) -> SessionRecoveryResponse:
    store = get_learning_store()
    health = store.health_check()
    if not health.get("available"):
        raise HTTPException(
            status_code=503,
            detail={
                "message": "持久化恢复不可用。",
                "actionable_hint": "检查本地 SQLite 配置；不要伪造学习状态。",
            },
        )
    progress = store.get_progress(student_id)
    traces = store.list_trace_summaries(student_id, session_id=session_id, limit=5)
    if progress is None and not traces:
        return SessionRecoveryResponse(
            student_id=student_id,
            session_id=session_id,
            progress_version=0,
            recovered=False,
            message="未找到可恢复的学习会话快照。",
        )
    recommendation_basis: list[dict] = []
    if traces:
        recommendation_basis = list(traces[0].get("recommendation_basis") or [])
    elif progress is not None:
        recommendation_basis = list(progress.recommendation_history[-3:])
    return SessionRecoveryResponse(
        student_id=student_id,
        session_id=session_id,
        progress_version=progress.version if progress else 0,
        concept_states=[item.model_dump() for item in progress.concept_states]
        if progress
        else [],
        weak_concepts=list(progress.weak_concepts) if progress else [],
        recommendation_basis=recommendation_basis,
        recent_trace_summaries=traces,
        recovered=True,
        message="已从本地持久化恢复 progress 与 TeachingTrace 摘要。",
    )


def _runtime_provider_gaps() -> list[dict[str, object]]:
    loop = getattr(events_api, "learning_loop", None)
    providers = [
        ("memory", getattr(loop, "memories", None)),
        ("rag", getattr(loop, "rag", None)),
    ]
    gaps: list[dict[str, object]] = []
    seen: set[tuple[str, str, str, str]] = set()
    for component, provider in providers:
        raw_gaps = getattr(provider, "last_evidence_gaps", [])
        if not isinstance(raw_gaps, list):
            continue
        for gap in raw_gaps:
            if not isinstance(gap, dict):
                continue
            health_gap = {"health_component": component, **gap}
            key = (
                str(health_gap.get("gap_type") or health_gap.get("category") or ""),
                str(health_gap.get("provider") or ""),
                str(health_gap.get("operation") or ""),
                str(health_gap.get("reason") or health_gap.get("message") or ""),
            )
            if key in seen:
                continue
            seen.add(key)
            gaps.append(health_gap)
    return gaps
