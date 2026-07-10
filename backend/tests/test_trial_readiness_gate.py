from __future__ import annotations

import json
from pathlib import Path

from fastapi.testclient import TestClient

from backend.app.core.config import MathTutorSettings
from backend.app.main import create_app
from backend.app.provider_health import build_provider_health
from backend.app.readiness.gate import build_trial_readiness_report
from backend.app.schemas.learning import ConceptState, KTLearningProgress, LearningEvent
from backend.app.storage.sqlite_store import SqliteLearningStore


SCRATCH = Path(
    "/var/folders/fd/p49ht4h53p9f30pmqm84t1p80000gp/T/grok-goal-f3abcd2e3523/implementer"
)


def test_trial_readiness_gate_default_fallback_is_not_internal_trial_ready(
    tmp_path: Path,
) -> None:
    store = SqliteLearningStore(tmp_path / "gate.sqlite")
    settings = MathTutorSettings()
    report = build_trial_readiness_report(
        settings=settings,
        provider_health=build_provider_health(settings=settings),
        store=store,
        probe_summaries=[],
    )

    assert report.status in {"ready", "degraded", "not_ready"}
    assert report.status == "not_ready"
    assert report.demo_runnable is True
    assert report.internal_trial_ready is False
    assert report.fallback_is_not_trial_ready is True
    assert report.human_decision_required is True
    assert "不得写入" in report.boundary or "只读" in report.boundary
    assert report.summary

    components = {item.component: item for item in report.components}
    assert "provider_configuration" in components
    assert "artifact_readiness" in components
    assert "persistence" in components
    assert "runtime_context_governance" in components
    assert "default_fallback_safety" in components
    assert components["default_fallback_safety"].status == "ready"
    assert components["artifact_readiness"].status == "degraded"
    assert components["persistence"].status == "ready"
    for item in report.components:
        assert item.reason
        assert item.actionable_hint

    serialized = json.dumps(report.model_dump(mode="json"), ensure_ascii=False)
    for forbidden in (
        "api_key",
        "authorization",
        "/Users/",
        ".pt",
        ".ckpt",
        "raw_provider_payload",
    ):
        assert forbidden not in serialized

    SCRATCH.mkdir(parents=True, exist_ok=True)
    (SCRATCH / "gate-default.json").write_text(
        json.dumps(report.model_dump(mode="json"), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def test_trial_readiness_api_is_read_only_and_exposed() -> None:
    client = TestClient(create_app())
    before = client.get("/api/trial-readiness")
    assert before.status_code == 200
    body = before.json()
    assert body["status"] in {"ready", "degraded", "not_ready"}
    assert body["demo_runnable"] is True
    assert body["internal_trial_ready"] is False
    assert body["components"]
    assert body["checklist"]

    # Gate read must not create progress for a random student.
    store = SqliteLearningStore()
    assert store.get_progress("student-gate-readonly-probe") is None


def test_gate_does_not_mutate_existing_progress(tmp_path: Path) -> None:
    store = SqliteLearningStore(tmp_path / "progress.sqlite")
    progress = KTLearningProgress(
        student_id="student-gate-no-write",
        version=3,
        concept_states=[
            ConceptState(
                concept_id="c_frac",
                concept_name="分数",
                mastery=0.42,
            )
        ],
        weak_concepts=[{"concept_id": "c_frac", "score": 0.8}],
        teaching_trace_ids=["tt-keep"],
    )
    store.save_progress(progress)
    before = store.get_progress("student-gate-no-write")
    assert before is not None

    build_trial_readiness_report(
        settings=MathTutorSettings(),
        store=store,
        probe_summaries=[],
    )
    after = store.get_progress("student-gate-no-write")
    assert after is not None
    assert after.version == 3
    assert after.concept_states[0].mastery == 0.42
    assert after.teaching_trace_ids == ["tt-keep"]
    assert after.weak_concepts == before.weak_concepts
