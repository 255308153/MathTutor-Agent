from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from backend.app.api import events as events_api
from backend.app.core.config import MathTutorSettings
from backend.app.main import create_app
from backend.app.provider_health import build_provider_health


ROOT = Path(__file__).resolve().parents[2]
IMPORTED_CONTENT = ROOT / "data" / "imported" / "assist2017_fixture" / "content_import.json"
IMPORTED_RAG = ROOT / "data" / "imported" / "assist2017_fixture" / "rag_documents.json"
DGEKT_OFFLINE_EVIDENCE_FIXTURE = ROOT / "data" / "dgekt" / "offline_evidence_fixture"


def test_health_check_returns_ok() -> None:
    client = TestClient(create_app())

    response = client.get("/api/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_provider_health_default_contract_reports_local_fallback_readiness() -> None:
    client = TestClient(create_app())

    response = client.get("/api/provider-health")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "healthy"
    assert body["summary"] == "默认本地 fallback / mock / demo provider 状态可运行。"
    _assert_iso_timestamp(body["generated_at"])

    components = {item["component"]: item for item in body["components"]}
    assert set(components) == {
        "memory",
        "rag",
        "kt",
        "content_rag_artifact",
        "learning_context",
    }

    for component in components.values():
        assert set(component) >= {
            "component",
            "display_name",
            "mode",
            "provider",
            "configured",
            "status",
            "severity",
            "recoverable",
            "actionable_hint",
            "evidence_gaps",
            "last_checked_at",
        }
        assert component["configured"] is True
        assert component["status"] in {
            "healthy",
            "degraded",
            "unavailable",
            "not_configured",
        }
        assert component["status"] == "healthy"
        assert component["severity"] == "info"
        assert component["recoverable"] is True
        assert component["evidence_gaps"] == []
        assert component["actionable_hint"]
        _assert_iso_timestamp(component["last_checked_at"])

    assert components["memory"]["mode"] == "local_fallback"
    assert components["memory"]["provider"] == "local_fallback"
    assert "本地长期记忆 fallback 可运行" in components["memory"]["actionable_hint"]
    assert components["rag"]["mode"] == "local_fallback"
    assert components["rag"]["provider"] == "local_fallback"
    assert "本地 RAG fallback 可运行" in components["rag"]["actionable_hint"]
    assert components["kt"]["mode"] == "mock"
    assert components["kt"]["provider"] == "mock"
    assert "mock KT 可运行" in components["kt"]["actionable_hint"]
    assert components["content_rag_artifact"]["mode"] == "content:demo/rag:demo"
    assert components["content_rag_artifact"]["provider"] == "demo_artifacts"
    assert "demo content 与 demo RAG artifact 可运行" in (
        components["content_rag_artifact"]["actionable_hint"]
    )
    assert components["learning_context"]["provider"] == "in_memory_context_layer"
    assert "只汇总 evidence" in components["learning_context"]["actionable_hint"]

    serialized = json.dumps(body, ensure_ascii=False)
    for forbidden in (
        "api_key",
        "authorization",
        "raw_provider_payload",
        "sdk_response",
        "embedding_vector",
        "provider_debug",
        ".pkl",
        ".pt",
        ".pth",
        ".ckpt",
        ".safetensors",
    ):
        assert forbidden not in serialized.lower()


def test_provider_health_reports_fake_memory_and_rag_without_credentials() -> None:
    health = build_provider_health(
        MathTutorSettings(
            memory_provider_mode="fake_provider",
            rag_provider_mode="fake_provider",
        )
    )

    body = health.model_dump()
    components = {item["component"]: item for item in body["components"]}

    assert body["status"] == "healthy"
    assert components["memory"]["provider"] == "fake_mem0_fixture"
    assert components["memory"]["mode"] == "fake_provider"
    assert components["memory"]["status"] == "healthy"
    assert "fake provider fixture 可运行" in components["memory"]["actionable_hint"]
    assert components["rag"]["provider"] == "fake_vikingdb_fixture"
    assert components["rag"]["mode"] == "fake_provider"
    assert components["rag"]["status"] == "healthy"
    assert "fake RAG provider fixture 可运行" in components["rag"]["actionable_hint"]


def test_provider_health_reports_memory_live_provider_missing_configuration() -> None:
    health = build_provider_health(MathTutorSettings(memory_provider_mode="live_provider"))

    body = health.model_dump()
    memory = {item["component"]: item for item in body["components"]}["memory"]

    assert body["status"] == "degraded"
    assert memory["provider"] == "mem0"
    assert memory["mode"] == "live_provider"
    assert memory["configured"] is False
    assert memory["status"] == "not_configured"
    assert memory["severity"] == "warning"
    assert "MATHTUTOR_MEM0_API_KEY" in memory["actionable_hint"]
    assert memory["evidence_gaps"][0]["gap_type"] == "provider_configuration_missing"
    assert memory["evidence_gaps"][0]["details"]["missing_fields"] == [
        "MATHTUTOR_MEM0_API_KEY"
    ]


def test_provider_health_reports_rag_live_provider_missing_configuration() -> None:
    health = build_provider_health(
        MathTutorSettings(
            rag_provider_mode="live_provider",
            rag_live_provider="openviking",
        )
    )

    body = health.model_dump()
    rag = {item["component"]: item for item in body["components"]}["rag"]

    assert body["status"] == "degraded"
    assert rag["provider"] == "openviking"
    assert rag["mode"] == "live_provider"
    assert rag["configured"] is False
    assert rag["status"] == "not_configured"
    assert rag["severity"] == "warning"
    missing_fields = rag["evidence_gaps"][0]["details"]["missing_fields"]
    assert set(missing_fields) == {
        "MATHTUTOR_RAG_PROVIDER_ENDPOINT",
        "MATHTUTOR_RAG_PROVIDER_COLLECTION",
        "MATHTUTOR_OPENVIKING_API_KEY",
    }
    assert "补齐配置或切回默认 local_fallback" in rag["actionable_hint"]


def test_provider_health_reports_missing_rag_live_provider_selection() -> None:
    settings_payload = MathTutorSettings().model_dump()
    settings_payload.update(
        {
            "rag_provider_mode": "live_provider",
            "rag_live_provider": "",
        }
    )
    settings = MathTutorSettings.model_construct(**settings_payload)

    health = build_provider_health(settings)
    rag = {item.component: item.model_dump() for item in health.components}["rag"]

    assert rag["provider"] == "vikingdb/openviking"
    assert rag["status"] == "not_configured"
    assert "MATHTUTOR_RAG_LIVE_PROVIDER" in rag["evidence_gaps"][0]["details"]["missing_fields"]


def test_provider_health_live_configuration_does_not_expose_secret_values() -> None:
    health = build_provider_health(
        MathTutorSettings(
            memory_provider_mode="live_provider",
            mem0_api_key="mem0-secret-value",
            rag_provider_mode="live_provider",
            rag_live_provider="vikingdb",
            vikingdb_api_key="viking-secret-value",
            rag_provider_endpoint="https://provider.example.test/search",
            rag_provider_collection="assist2017-smoke",
        )
    )

    body = health.model_dump()
    components = {item["component"]: item for item in body["components"]}

    assert components["memory"]["status"] == "healthy"
    assert components["memory"]["evidence_gaps"] == []
    assert components["rag"]["status"] == "healthy"
    assert components["rag"]["evidence_gaps"] == []
    serialized = json.dumps(body, ensure_ascii=False)
    assert "mem0-secret-value" not in serialized
    assert "viking-secret-value" not in serialized


@pytest.mark.parametrize(
    ("gap_type", "expected_status", "expected_severity", "expected_message"),
    [
        ("provider_failure", "unavailable", "error", "provider evidence 当前不可用。"),
        ("provider_timeout", "unavailable", "warning", "provider 请求超时。"),
        ("provider_auth_error", "unavailable", "error", "provider 凭据或权限不可用。"),
        ("provider_empty_result", "degraded", "info", "provider 未返回可用 evidence。"),
        ("provider_schema_mismatch", "degraded", "warning", "provider 响应无法规范化。"),
        ("provider_budget_exceeded", "degraded", "warning", "provider quota、rate limit 或预算已触发。"),
    ],
)
def test_provider_health_normalizes_provider_gap_categories(
    gap_type: str,
    expected_status: str,
    expected_severity: str,
    expected_message: str,
) -> None:
    health = build_provider_health(
        MathTutorSettings(
            memory_provider_mode="live_provider",
            mem0_api_key="configured-key",
        ),
        provider_gaps=[
            {
                "gap_type": gap_type,
                "provider": "mem0",
                "operation": "search",
                "reason": "Authorization: Bearer live-secret api_key=also-secret",
                "details": {
                    "safe_summary": "保留安全摘要",
                    "raw_provider_payload": {"secret": "raw-secret"},
                    "sdk_response": {"debug": "sdk-secret"},
                    "embedding_vector": [0.1, 0.2, 0.3],
                    "provider_debug": {"token": "debug-secret"},
                    "cache_path": "/Users/lqc/private/provider-cache/live-secret.bin",
                },
            }
        ],
    )

    body = health.model_dump()
    memory = {item["component"]: item for item in body["components"]}["memory"]
    gap = memory["evidence_gaps"][0]

    assert body["status"] == expected_status
    assert memory["status"] == expected_status
    assert memory["severity"] == expected_severity
    assert memory["actionable_hint"] == gap["actionable_hint"]
    assert gap["gap_type"] == gap_type
    assert gap["code"] == gap_type
    assert gap["category"] == gap_type
    assert gap["provider"] == "mem0"
    assert gap["operation"] == "search"
    assert gap["status"] == expected_status
    assert gap["severity"] == expected_severity
    assert gap["recoverable"] is True
    assert gap["message"] == expected_message
    assert gap["impact"]
    assert gap["actionable_hint"]
    assert gap["details"]["safe_summary"] == "保留安全摘要"
    assert gap["details"]["cache_path"] == "<local_path_redacted>"

    serialized = json.dumps(body, ensure_ascii=False).lower()
    for forbidden in (
        "live-secret",
        "also-secret",
        "raw-secret",
        "sdk-secret",
        "debug-secret",
        "authorization",
        "api_key",
        "raw_provider_payload",
        "sdk_response",
        "embedding_vector",
        "provider_debug",
        "/users/lqc/private",
    ):
        assert forbidden not in serialized


def test_provider_health_reads_runtime_provider_gaps_without_mutating_them(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runtime_gap = {
        "gap_type": "provider_timeout",
        "provider": "openviking",
        "operation": "search",
        "reason": "provider timed out with Bearer runtime-secret",
        "details": {"safe_summary": "最近一次 RAG provider 搜索超时"},
    }
    provider = _RuntimeProvider([runtime_gap])
    monkeypatch.setattr(
        events_api,
        "learning_loop",
        _RuntimeLoop(memories=_RuntimeProvider([]), rag=provider),
    )
    client = TestClient(create_app())

    response = client.get("/api/provider-health")

    assert response.status_code == 200
    body = response.json()
    rag = {item["component"]: item for item in body["components"]}["rag"]
    assert rag["status"] == "unavailable"
    assert rag["evidence_gaps"][0]["gap_type"] == "provider_timeout"
    assert rag["evidence_gaps"][0]["message"] == "provider 请求超时。"
    assert provider.last_evidence_gaps == [runtime_gap]
    assert "runtime-secret" not in json.dumps(body, ensure_ascii=False)


def test_provider_health_degraded_snapshot_does_not_block_default_learning_flow() -> None:
    degraded_health = build_provider_health(
        MathTutorSettings(
            memory_provider_mode="live_provider",
            rag_provider_mode="live_provider",
        )
    )
    assert degraded_health.status == "degraded"

    client = TestClient(create_app())
    response = client.post(
        "/api/events",
        json={
            "session_id": "session-provider-health-readiness",
            "student_id": "student-provider-health-readiness",
            "type": "chat_message",
            "message": "我下一步应该练什么？",
            "payload": {},
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["recommended_questions"]
    assert body["state_summary"]["errors"] == []


def test_provider_health_reports_dgekt_missing_checkpoint_dataset_and_q_matrix() -> None:
    health = build_provider_health(MathTutorSettings(kt_engine="dgekt"))

    body = health.model_dump()
    kt = {item["component"]: item for item in body["components"]}["kt"]

    assert body["status"] == "degraded"
    assert kt["provider"] == "dgekt"
    assert kt["mode"] == "dgekt"
    assert kt["configured"] is False
    assert kt["status"] == "not_configured"
    assert kt["severity"] == "warning"
    missing_fields = kt["evidence_gaps"][0]["details"]["missing_fields"]
    assert set(missing_fields) == {
        "MATHTUTOR_DGEKT_CHECKPOINT_PATH",
        "MATHTUTOR_DGEKT_DATASET_DIR",
        "MATHTUTOR_DGEKT_Q_MATRIX_PATH",
    }
    assert "补齐 env 或切回默认 mock KT" in kt["actionable_hint"]


def test_provider_health_reports_dgekt_missing_dataset_and_q_matrix_after_checkpoint(
    tmp_path: Path,
) -> None:
    checkpoint = tmp_path / "checkpoint.fixture"
    checkpoint.write_text("not a real checkpoint", encoding="utf-8")

    health = build_provider_health(
        MathTutorSettings(
            kt_engine="dgekt",
            dgekt_checkpoint_path=str(checkpoint),
        )
    )
    kt = {item.component: item.model_dump() for item in health.components}["kt"]

    assert kt["status"] == "not_configured"
    missing_fields = kt["evidence_gaps"][0]["details"]["missing_fields"]
    assert missing_fields == [
        "MATHTUTOR_DGEKT_DATASET_DIR",
        "MATHTUTOR_DGEKT_Q_MATRIX_PATH",
    ]


def test_provider_health_reports_dgekt_unavailable_paths_without_leaking_paths(
    tmp_path: Path,
) -> None:
    health = build_provider_health(
        MathTutorSettings(
            kt_engine="dgekt",
            dgekt_checkpoint_path=str(tmp_path / "private-checkpoint.fixture"),
            dgekt_dataset_dir=str(tmp_path / "private-dataset"),
            dgekt_q_matrix_path=str(tmp_path / "private-q-matrix.csv"),
            dgekt_canonical_mapping_path=str(tmp_path / "private-mapping.json"),
            dgekt_offline_evidence_dir=str(tmp_path / "private-offline-evidence"),
        )
    )

    body = health.model_dump()
    kt = {item["component"]: item for item in body["components"]}["kt"]

    assert kt["status"] == "unavailable"
    assert kt["severity"] == "error"
    artifact_gaps = [
        gap for gap in kt["evidence_gaps"] if gap["gap_type"] == "missing_artifact"
    ]
    assert artifact_gaps
    serialized = json.dumps(body, ensure_ascii=False)
    assert "private-checkpoint" not in serialized
    assert "private-dataset" not in serialized
    assert "private-q-matrix" not in serialized
    assert "private-mapping" not in serialized
    assert "private-offline-evidence" not in serialized


def test_provider_health_reports_dgekt_partial_offline_evidence_when_not_configured(
    tmp_path: Path,
) -> None:
    checkpoint, dataset_dir, q_matrix = _write_dgekt_readiness_files(tmp_path)

    health = build_provider_health(
        MathTutorSettings(
            kt_engine="dgekt",
            dgekt_checkpoint_path=str(checkpoint),
            dgekt_dataset_dir=str(dataset_dir),
            dgekt_q_matrix_path=str(q_matrix),
        )
    )
    kt = {item.component: item.model_dump() for item in health.components}["kt"]

    assert health.status == "degraded"
    assert kt["configured"] is True
    assert kt["status"] == "degraded"
    assert "partial readiness" in kt["actionable_hint"]
    offline_gap = next(
        gap for gap in kt["evidence_gaps"] if gap["code"] == "offline_evidence_not_configured"
    )
    assert offline_gap["details"]["offline_evidence_status"] == "partial"
    assert "complete offline evidence" in offline_gap["actionable_hint"]


def test_provider_health_reports_dgekt_complete_fixture_readiness(tmp_path: Path) -> None:
    checkpoint, dataset_dir, q_matrix = _write_dgekt_readiness_files(tmp_path)

    health = build_provider_health(
        MathTutorSettings(
            kt_engine="dgekt",
            dgekt_checkpoint_path=str(checkpoint),
            dgekt_dataset_dir=str(dataset_dir),
            dgekt_q_matrix_path=str(q_matrix),
            dgekt_offline_evidence_dir=str(DGEKT_OFFLINE_EVIDENCE_FIXTURE),
        )
    )
    kt = {item.component: item.model_dump() for item in health.components}["kt"]

    assert kt["status"] == "healthy"
    assert kt["severity"] == "info"
    assert kt["evidence_gaps"] == []
    assert "offline evidence 基础 artifact 均可诊断" in kt["actionable_hint"]


def test_provider_health_reports_imported_content_and_rag_fixture_readiness() -> None:
    health = build_provider_health(
        MathTutorSettings(
            content_source="imported",
            content_import_path=str(IMPORTED_CONTENT),
            rag_source="imported",
            rag_artifact_path=str(IMPORTED_RAG),
        )
    )
    components = {item.component: item.model_dump() for item in health.components}
    artifacts = components["content_rag_artifact"]
    context = components["learning_context"]

    assert artifacts["status"] == "healthy"
    assert artifacts["provider"] == "fixture_artifacts"
    assert artifacts["mode"] == "content:imported/rag:imported"
    assert "不覆盖 KT facts" in artifacts["actionable_hint"]
    assert context["mode"] == "context_evidence_assembly"
    assert "只保留 evidence gap，不改写学习事实" in context["actionable_hint"]


def test_provider_health_reports_missing_imported_content_and_rag_configuration() -> None:
    health = build_provider_health(
        MathTutorSettings(
            content_source="imported",
            rag_source="imported",
        )
    )
    artifacts = {item.component: item.model_dump() for item in health.components}[
        "content_rag_artifact"
    ]

    assert health.status == "degraded"
    assert artifacts["status"] == "not_configured"
    assert artifacts["severity"] == "warning"
    assert set(artifacts["evidence_gaps"][0]["details"]["missing_fields"]) == {
        "MATHTUTOR_CONTENT_IMPORT_PATH",
        "MATHTUTOR_RAG_ARTIFACT_PATH",
    }


def test_provider_health_reports_unavailable_imported_artifact_paths_without_leaking_paths(
    tmp_path: Path,
) -> None:
    health = build_provider_health(
        MathTutorSettings(
            content_source="imported",
            content_import_path=str(tmp_path / "private-content.json"),
            rag_source="imported",
            rag_artifact_path=str(tmp_path / "private-rag.json"),
        )
    )
    body = health.model_dump()
    artifacts = {item["component"]: item for item in body["components"]}[
        "content_rag_artifact"
    ]

    assert body["status"] == "unavailable"
    assert artifacts["status"] == "unavailable"
    assert artifacts["severity"] == "error"
    assert artifacts["evidence_gaps"][0]["details"]["missing_artifacts"] == [
        "imported content_import.json",
        "imported rag_documents.json",
    ]
    serialized = json.dumps(body, ensure_ascii=False)
    assert "private-content" not in serialized
    assert "private-rag" not in serialized


def test_provider_health_does_not_change_kt_facts() -> None:
    client = TestClient(create_app())
    event_payload = {
        "session_id": "session-provider-health-kt-readonly",
        "student_id": "student-provider-health-kt-readonly",
        "type": "chat_message",
        "message": "我下一步应该练什么？",
        "payload": {},
    }
    before = client.post("/api/events", json=event_payload).json()["state_summary"]

    health = client.get("/api/provider-health")

    after = client.post("/api/events", json=event_payload).json()["state_summary"]
    assert health.status_code == 200
    for field in ("concept_states", "weak_concepts", "forgetting_risks"):
        assert after[field] == before[field]


def _assert_iso_timestamp(value: str) -> None:
    parsed = datetime.fromisoformat(value)
    assert parsed.tzinfo is not None


class _RuntimeProvider:
    def __init__(self, gaps: list[dict[str, object]]) -> None:
        self.last_evidence_gaps = gaps


class _RuntimeLoop:
    def __init__(self, *, memories: _RuntimeProvider, rag: _RuntimeProvider) -> None:
        self.memories = memories
        self.rag = rag


def _write_dgekt_readiness_files(tmp_path: Path) -> tuple[Path, Path, Path]:
    checkpoint = tmp_path / "checkpoint.fixture"
    checkpoint.write_text("not a real checkpoint", encoding="utf-8")
    dataset_dir = tmp_path / "assist2017"
    dataset_dir.mkdir()
    for filename in ("assist2017_pid_train.csv", "assist2017_pid_test.csv"):
        (dataset_dir / filename).write_text("fixture\n", encoding="utf-8")
    q_matrix = tmp_path / "q_matrix.csv"
    q_matrix.write_text("1,0\n0,1\n", encoding="utf-8")
    return checkpoint, dataset_dir, q_matrix
