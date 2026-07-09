from __future__ import annotations

from collections.abc import Iterable
from datetime import UTC, datetime
from typing import Any

from .core.config import MathTutorSettings, get_settings
from .schemas.provider_health import (
    ProviderHealthComponent,
    ProviderHealthResponse,
    ProviderHealthStatus,
)


def build_provider_health(
    settings: MathTutorSettings | None = None,
) -> ProviderHealthResponse:
    active_settings = settings or get_settings()
    checked_at = datetime.now(UTC).isoformat()
    components = [
        _memory_health(active_settings, checked_at),
        _rag_health(active_settings, checked_at),
        _kt_health(active_settings, checked_at),
        _content_rag_artifact_health(active_settings, checked_at),
        _learning_context_health(active_settings, checked_at),
    ]
    status = _overall_status(component.status for component in components)
    return ProviderHealthResponse(
        status=status,
        summary=_summary(status),
        generated_at=checked_at,
        components=components,
    )


def _memory_health(
    settings: MathTutorSettings,
    checked_at: str,
) -> ProviderHealthComponent:
    mode = settings.memory_provider_mode
    if mode == "live_provider":
        missing_fields = [] if settings.mem0_api_key else ["MATHTUTOR_MEM0_API_KEY"]
        configured = not missing_fields
        hint = (
            "Mem0 live provider 已显式启用并具备基础配置；本健康检查不访问外部网络。"
            if configured
            else "Mem0 live provider 已显式启用，但缺少 MATHTUTOR_MEM0_API_KEY；"
            "补齐凭据或切回默认 local_fallback。"
        )
        return ProviderHealthComponent(
            component="memory",
            display_name="Memory / 长期记忆",
            mode=mode,
            provider="mem0",
            configured=configured,
            status="healthy" if configured else "not_configured",
            severity="info" if configured else "warning",
            recoverable=True,
            actionable_hint=hint,
            evidence_gaps=_configuration_gaps(
                provider="mem0",
                operation="memory_readiness",
                missing_fields=missing_fields,
                hint=hint,
            ),
            last_checked_at=checked_at,
        )
    if mode == "fake_provider":
        return ProviderHealthComponent(
            component="memory",
            display_name="Memory / 长期记忆",
            mode=mode,
            provider="fake_mem0_fixture",
            configured=True,
            status="healthy",
            severity="info",
            recoverable=True,
            actionable_hint="fake provider fixture 可运行；仅用于无网络、无密钥的测试诊断。",
            last_checked_at=checked_at,
        )
    return ProviderHealthComponent(
        component="memory",
        display_name="Memory / 长期记忆",
        mode=mode,
        provider="local_fallback",
        configured=True,
        status="healthy",
        severity="info",
        recoverable=True,
        actionable_hint="默认本地长期记忆 fallback 可运行；Mem0 live provider 未启用。",
        last_checked_at=checked_at,
    )


def _rag_health(settings: MathTutorSettings, checked_at: str) -> ProviderHealthComponent:
    mode = settings.rag_provider_mode
    if mode == "live_provider":
        provider = str(settings.rag_live_provider or "").strip()
        provider_known = provider in {"vikingdb", "openviking"}
        api_key = (
            settings.openviking_api_key
            if provider == "openviking"
            else settings.vikingdb_api_key
        )
        missing_fields = []
        if not provider_known:
            missing_fields.append("MATHTUTOR_RAG_LIVE_PROVIDER")
        if not settings.rag_provider_endpoint:
            missing_fields.append("MATHTUTOR_RAG_PROVIDER_ENDPOINT")
        if not settings.rag_provider_collection:
            missing_fields.append("MATHTUTOR_RAG_PROVIDER_COLLECTION")
        if not api_key:
            missing_fields.append(
                "MATHTUTOR_OPENVIKING_API_KEY"
                if provider == "openviking"
                else "MATHTUTOR_VIKINGDB_API_KEY"
            )
        configured = not missing_fields
        provider_name = provider if provider_known else "vikingdb/openviking"
        hint = (
            f"{provider_name} live RAG 已显式启用并具备基础配置；本健康检查不访问外部网络。"
            if configured
            else f"{provider_name} live RAG 已显式启用，但缺少 "
            f"{'、'.join(missing_fields)}；补齐配置或切回默认 local_fallback。"
        )
        return ProviderHealthComponent(
            component="rag",
            display_name="RAG / 知识检索",
            mode=mode,
            provider=provider_name,
            configured=configured,
            status="healthy" if configured else "not_configured",
            severity="info" if configured else "warning",
            recoverable=True,
            actionable_hint=hint,
            evidence_gaps=_configuration_gaps(
                provider=provider_name,
                operation="rag_readiness",
                missing_fields=missing_fields,
                hint=hint,
            ),
            last_checked_at=checked_at,
        )
    if mode == "fake_provider":
        return ProviderHealthComponent(
            component="rag",
            display_name="RAG / 知识检索",
            mode=mode,
            provider="fake_vikingdb_fixture",
            configured=True,
            status="healthy",
            severity="info",
            recoverable=True,
            actionable_hint="fake RAG provider fixture 可运行；仅用于无网络、无密钥的测试诊断。",
            last_checked_at=checked_at,
        )
    return ProviderHealthComponent(
        component="rag",
        display_name="RAG / 知识检索",
        mode=mode,
        provider="local_fallback",
        configured=True,
        status="healthy",
        severity="info",
        recoverable=True,
        actionable_hint="默认本地 RAG fallback 可运行；VikingDB / OpenViking live provider 未启用。",
        last_checked_at=checked_at,
    )


def _kt_health(settings: MathTutorSettings, checked_at: str) -> ProviderHealthComponent:
    if settings.kt_engine == "dgekt":
        configured = bool(
            settings.dgekt_checkpoint_path
            and settings.dgekt_dataset_dir
            and settings.dgekt_q_matrix_path
        )
        return ProviderHealthComponent(
            component="kt",
            display_name="KT / DGEKT",
            mode=settings.kt_engine,
            provider="dgekt",
            configured=configured,
            status="healthy" if configured else "not_configured",
            severity="info" if configured else "warning",
            recoverable=True,
            actionable_hint=(
                "DGEKT 已显式启用并具备 checkpoint、dataset_dir 与 Q-matrix 基础配置。"
                if configured
                else "DGEKT 已显式启用，但缺少 checkpoint、dataset_dir 或 Q-matrix；"
                "补齐配置或切回默认 mock KT。"
            ),
            last_checked_at=checked_at,
        )
    return ProviderHealthComponent(
        component="kt",
        display_name="KT / DGEKT",
        mode=settings.kt_engine,
        provider="mock",
        configured=True,
        status="healthy",
        severity="info",
        recoverable=True,
        actionable_hint="默认 mock KT 可运行；真实 DGEKT checkpoint 未启用，KT facts 仍是权威学习事实。",
        last_checked_at=checked_at,
    )


def _content_rag_artifact_health(
    settings: MathTutorSettings,
    checked_at: str,
) -> ProviderHealthComponent:
    content_configured = settings.content_source == "demo" or bool(settings.content_import_path)
    rag_configured = settings.rag_source == "demo" or bool(settings.rag_artifact_path)
    configured = content_configured and rag_configured
    mode = f"content:{settings.content_source}/rag:{settings.rag_source}"
    return ProviderHealthComponent(
        component="content_rag_artifact",
        display_name="Content/RAG artifact",
        mode=mode,
        provider="demo_artifacts" if configured else "imported_artifacts",
        configured=configured,
        status="healthy" if configured else "not_configured",
        severity="info" if configured else "warning",
        recoverable=True,
        actionable_hint=(
            "默认 demo content 与 demo RAG artifact 可运行；当前未要求 full ASSISTments2017 或 generated vector index。"
            if configured
            else "已选择 imported content 或 RAG artifact，但缺少导入路径；补齐路径或切回 demo。"
        ),
        last_checked_at=checked_at,
    )


def _learning_context_health(
    settings: MathTutorSettings,
    checked_at: str,
) -> ProviderHealthComponent:
    return ProviderHealthComponent(
        component="learning_context",
        display_name="LearningContextLayer",
        mode="local_fallback",
        provider="in_memory_context_layer",
        configured=True,
        status="healthy",
        severity="info",
        recoverable=True,
        actionable_hint=(
            "LearningContextLayer 使用本地上下文组装证据；它只汇总 evidence，不决定 mastery 或 KT facts。"
        ),
        last_checked_at=checked_at,
    )


def _overall_status(statuses: Iterable[ProviderHealthStatus]) -> ProviderHealthStatus:
    status_set = set(statuses)
    if "unavailable" in status_set:
        return "unavailable"
    if "degraded" in status_set:
        return "degraded"
    if "not_configured" in status_set:
        return "degraded"
    return "healthy"


def _configuration_gaps(
    *,
    provider: str,
    operation: str,
    missing_fields: list[str],
    hint: str,
) -> list[dict[str, Any]]:
    if not missing_fields:
        return []
    return [
        {
            "gap_type": "provider_configuration_missing",
            "code": "provider_configuration_missing",
            "category": "provider_configuration_missing",
            "provider": provider,
            "operation": operation,
            "reason": f"{provider} readiness 缺少必要配置：{'、'.join(missing_fields)}。",
            "message": f"{provider} readiness 缺少必要配置。",
            "severity": "warning",
            "recoverable": True,
            "actionable_hint": hint,
            "details": {"missing_fields": missing_fields},
        }
    ]


def _summary(status: ProviderHealthStatus) -> str:
    return {
        "healthy": "默认本地 fallback / mock / demo provider 状态可运行。",
        "degraded": "部分 provider 未配置或处于降级状态，默认学习流程仍可继续。",
        "unavailable": "存在不可用 provider，请先查看组件恢复建议。",
        "not_configured": "provider 尚未配置，请查看组件恢复建议。",
    }[status]
