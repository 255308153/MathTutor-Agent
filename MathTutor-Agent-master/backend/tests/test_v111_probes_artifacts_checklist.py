from __future__ import annotations

import json
from pathlib import Path

from fastapi.testclient import TestClient

from backend.app.core.config import MathTutorSettings
from backend.app.main import create_app
from backend.app.provider_health import build_provider_health
from backend.app.readiness.gate import build_trial_readiness_report
from backend.app.readiness.probes import run_canary_probes
from backend.app.storage.sqlite_store import SqliteLearningStore


SCRATCH = Path(
    "/var/folders/fd/p49ht4h53p9f30pmqm84t1p80000gp/T/grok-goal-f3abcd2e3523/implementer"
)
ROOT = Path(__file__).resolve().parents[2]


def test_canary_probes_default_skip_without_credentials(tmp_path: Path) -> None:
    store = SqliteLearningStore(tmp_path / "probe.sqlite")
    settings = MathTutorSettings(enable_provider_canary_probe=False)
    results = run_canary_probes(settings=settings, store=store)
    assert results
    assert all(item.skipped for item in results)
    assert all(item.status == "skipped" for item in results)

    report = build_trial_readiness_report(
        settings=settings,
        store=store,
        probe_summaries=results,
    )
    probe_component = next(
        item for item in report.components if item.component == "provider_canary_probe"
    )
    assert probe_component.status == "skipped"

    SCRATCH.mkdir(parents=True, exist_ok=True)
    (SCRATCH / "probe-default.log").write_text(
        json.dumps([item.model_dump(mode="json") for item in results], ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def test_canary_probes_opt_in_sanitized_without_live_network(tmp_path: Path) -> None:
    store = SqliteLearningStore(tmp_path / "probe-optin.sqlite")
    settings = MathTutorSettings(
        enable_provider_canary_probe=True,
        memory_provider_mode="live_provider",
        mem0_api_key="test-key-not-real",
        run_mem0_live_smoke=True,
        rag_provider_mode="live_provider",
        rag_live_provider="vikingdb",
        rag_provider_endpoint="https://example.invalid",
        rag_provider_collection="canary",
        vikingdb_api_key="test-viking-key",
        run_viking_rag_smoke=True,
    )
    results = run_canary_probes(
        settings=settings,
        store=store,
        canary_token="secret-canary-token-xyz",
    )
    assert results
    payload = json.dumps([item.model_dump(mode="json") for item in results], ensure_ascii=False)
    assert "test-key-not-real" not in payload
    assert "test-viking-key" not in payload
    assert "secret-canary-token-xyz" not in payload
    assert "/Users/" not in payload
    assert any(item.provider == "memory" for item in results)
    assert any(item.provider == "rag" for item in results)

    SCRATCH.mkdir(parents=True, exist_ok=True)
    (SCRATCH / "probe-canary.log").write_text(payload, encoding="utf-8")


def test_artifact_readiness_distinguishes_demo_missing_and_fixture(tmp_path: Path) -> None:
    store = SqliteLearningStore(tmp_path / "artifacts.sqlite")

    demo = build_trial_readiness_report(
        settings=MathTutorSettings(),
        store=store,
        probe_summaries=[],
    )
    demo_map = {item.component: item for item in demo.artifact_summaries}
    assert demo_map["dgekt_checkpoint"].status == "degraded"
    assert demo_map["imported_content"].status == "degraded"

    missing = build_trial_readiness_report(
        settings=MathTutorSettings(
            content_source="imported",
            content_import_path="",
            rag_source="imported",
            rag_artifact_path="",
            kt_engine="dgekt",
        ),
        store=store,
        probe_summaries=[],
    )
    assert missing.status in {"degraded", "not_ready"}
    missing_art = {item.component: item for item in missing.artifact_summaries}
    assert missing_art["imported_content"].status in {"degraded", "not_ready"}

    fixture_content = ROOT / "data" / "imported" / "assist2017_fixture" / "content_import.json"
    fixture_rag = ROOT / "data" / "imported" / "assist2017_fixture" / "rag_documents.json"
    configured = build_trial_readiness_report(
        settings=MathTutorSettings(
            content_source="imported",
            content_import_path=str(fixture_content),
            rag_source="imported",
            rag_artifact_path=str(fixture_rag),
        ),
        provider_health=build_provider_health(
            settings=MathTutorSettings(
                content_source="imported",
                content_import_path=str(fixture_content),
                rag_source="imported",
                rag_artifact_path=str(fixture_rag),
            )
        ),
        store=store,
        probe_summaries=[],
    )
    configured_art = {item.component: item for item in configured.artifact_summaries}
    assert configured_art["imported_content"].status in {"ready", "degraded"}
    blob = json.dumps(configured.model_dump(mode="json"), ensure_ascii=False)
    assert str(fixture_content) not in blob
    assert "/Users/" not in blob

    SCRATCH.mkdir(parents=True, exist_ok=True)
    (SCRATCH / "artifact-readiness.log").write_text(
        json.dumps(
            {
                "demo": [item.model_dump(mode="json") for item in demo.artifact_summaries],
                "missing_status": missing.status,
                "configured": [
                    item.model_dump(mode="json") for item in configured.artifact_summaries
                ],
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )


def test_trial_checklist_and_human_feedback_not_auto_ready(tmp_path: Path, monkeypatch) -> None:
    store = SqliteLearningStore(tmp_path / "trial.sqlite")
    from backend.app.storage import sqlite_store as sqlite_mod

    monkeypatch.setattr(sqlite_mod, "_STORE", store)
    client = TestClient(create_app())

    readiness = client.get("/api/trial-readiness")
    assert readiness.status_code == 200
    body = readiness.json()
    assert body["internal_trial_ready"] is False
    assert body["checklist"]
    assert any(item["item_id"] == "human_decision" for item in body["checklist"])
    assert body["human_decision_required"] is True

    feedback = client.post(
        "/api/trial-readiness/feedback",
        json={
            "student_flow": "完成答题+下一步建议+记忆禁用",
            "issue_category": "provider_gap",
            "impact": "暂不影响默认 demo",
            "handling_status": "open",
            "residual_risk": "真实 Mem0/Viking 未验证",
            "decision": "hold",
            "operator_note": "等待 canary 环境",
            "actor": "operator",
        },
    )
    assert feedback.status_code == 200
    assert feedback.json()["decision"] == "hold"

    after = client.get("/api/trial-readiness").json()
    assert after["recent_feedback"]
    assert after["recent_feedback"][0]["decision"] == "hold"
    assert after["internal_trial_ready"] is False

    SCRATCH.mkdir(parents=True, exist_ok=True)
    (SCRATCH / "trial-checklist.log").write_text(
        json.dumps(
            {
                "checklist": after["checklist"],
                "feedback": after["recent_feedback"][0],
                "internal_trial_ready": after["internal_trial_ready"],
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
