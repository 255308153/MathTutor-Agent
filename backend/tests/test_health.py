from __future__ import annotations

import json
from datetime import datetime

from fastapi.testclient import TestClient

from backend.app.core.config import MathTutorSettings
from backend.app.main import create_app
from backend.app.provider_health import build_provider_health


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


def _assert_iso_timestamp(value: str) -> None:
    parsed = datetime.fromisoformat(value)
    assert parsed.tzinfo is not None
