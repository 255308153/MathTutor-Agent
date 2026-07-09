from __future__ import annotations

import json
from datetime import datetime

from fastapi.testclient import TestClient

from backend.app.main import create_app


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


def _assert_iso_timestamp(value: str) -> None:
    parsed = datetime.fromisoformat(value)
    assert parsed.tzinfo is not None
