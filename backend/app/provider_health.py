from __future__ import annotations

from collections.abc import Iterable, Mapping
from datetime import UTC, datetime
from pathlib import Path
import re
from typing import Any

from .core.config import MathTutorSettings, get_settings
from .mapping.xes3g5m_mapping import DEFAULT_MAPPING_PATH
from .provider_gaps import PROVIDER_EVIDENCE_GAP_TYPES, RAW_PROVIDER_KEYS
from .rag.knowledge_rag import RAG_PATH
from .schemas.provider_health import (
    ProviderHealthComponent,
    ProviderHealthResponse,
    ProviderHealthStatus,
)
from .storage.content_repository import CONTENT_PATH


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DGEKT_DATASET_FILES = ("xes3g5m_pid_train.csv", "xes3g5m_pid_test.csv")
DGEKT_OFFLINE_EVIDENCE_FILES = (
    "diagnosis_cases.json",
    "attribution_paths.csv",
    "key_history.csv",
    "path_ablation.csv",
    "weak_concepts.csv",
)
PROVIDER_GAP_HEALTH = {
    "provider_configuration_missing": {
        "status": "not_configured",
        "severity": "warning",
        "message": "provider readiness 缺少必要配置。",
        "impact": "该 provider 已被显式选择但配置不完整；系统不会信任其 evidence，也不会阻塞默认本地学习流程。",
        "actionable_hint": "补齐对应 env / provider 配置，或切回 local_fallback / fake_provider 验证主流程。",
    },
    "provider_failure": {
        "status": "unavailable",
        "severity": "error",
        "message": "provider evidence 当前不可用。",
        "impact": "该 provider 暂时不能提供可信 evidence；默认学习流程继续使用可用的本地或 fixture evidence。",
        "actionable_hint": "查看 provider 服务状态、endpoint、网络和 adapter 日志；不要把失败 provider 的 evidence 写入学习事实。",
    },
    "provider_timeout": {
        "status": "unavailable",
        "severity": "warning",
        "message": "provider 请求超时。",
        "impact": "该 provider 本次未能按时返回 evidence；学习流程只能使用已有本地或 fixture evidence。",
        "actionable_hint": "检查 endpoint、网络和 timeout 配置；必要时切回 local_fallback 或 fake_provider 验证主流程。",
    },
    "provider_auth_error": {
        "status": "unavailable",
        "severity": "error",
        "message": "provider 凭据或权限不可用。",
        "impact": "系统不会信任认证失败 provider 的 evidence，也不会把失败原因写成 mastery 或 prediction facts。",
        "actionable_hint": "检查 API key、权限、provider 选择和本地 env 配置；不要把 credentials 提交到仓库。",
    },
    "provider_empty_result": {
        "status": "degraded",
        "severity": "info",
        "message": "provider 未返回可用 evidence。",
        "impact": "没有可用记忆或 citation 时，系统不会伪造 memory/RAG evidence。",
        "actionable_hint": "检查 query、metadata filter、namespace、collection 或学生记忆内容。",
    },
    "provider_schema_mismatch": {
        "status": "degraded",
        "severity": "warning",
        "message": "provider 响应无法规范化。",
        "impact": "malformed provider evidence 已被丢弃，不会进入 RAG citation、memory 或 KT facts。",
        "actionable_hint": "检查 provider SDK 返回字段、metadata 别名和 adapter schema。",
    },
    "provider_budget_exceeded": {
        "status": "degraded",
        "severity": "warning",
        "message": "provider quota、rate limit 或预算已触发。",
        "impact": "系统只使用已经取得的 evidence，不等待 provider 覆盖 KT facts。",
        "actionable_hint": "检查 quota、rate limit、调用预算和 provider 账单设置；必要时降低 live 调用频率。",
    },
}


def build_provider_health(
    settings: MathTutorSettings | None = None,
    provider_gaps: Iterable[Mapping[str, Any]] | None = None,
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
    components = _apply_provider_gaps(components, provider_gaps or [])
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
        missing_fields: list[str] = []
        missing_artifacts: list[str] = []
        if not settings.dgekt_checkpoint_path:
            missing_fields.append("MATHTUTOR_DGEKT_CHECKPOINT_PATH")
        elif not _resolve_project_path(settings.dgekt_checkpoint_path).is_file():
            missing_artifacts.append("DGEKT checkpoint file")

        if not settings.dgekt_dataset_dir:
            missing_fields.append("MATHTUTOR_DGEKT_DATASET_DIR")
        else:
            dataset_dir = _resolve_project_path(settings.dgekt_dataset_dir)
            if not dataset_dir.is_dir():
                missing_artifacts.append("DGEKT dataset directory")
            else:
                for filename in DGEKT_DATASET_FILES:
                    if not (dataset_dir / filename).is_file():
                        missing_artifacts.append(f"DGEKT dataset file {filename}")

        if not settings.dgekt_kc_routes_path:
            missing_fields.append("MATHTUTOR_DGEKT_Q_MATRIX_PATH")
        elif not _resolve_project_path(settings.dgekt_kc_routes_path).is_file():
            missing_artifacts.append("DGEKT KC routes file")

        mapping_path = (
            _resolve_project_path(settings.dgekt_canonical_mapping_path)
            if settings.dgekt_canonical_mapping_path
            else DEFAULT_MAPPING_PATH
        )
        if not mapping_path.is_file():
            missing_artifacts.append("DGEKT canonical mapping artifact")

        offline_gaps, offline_status = _dgekt_offline_evidence_gaps(settings)
        configured = not missing_fields and not missing_artifacts
        status: ProviderHealthStatus = "healthy"
        severity = "info"
        if missing_fields:
            status = "not_configured"
            severity = "warning"
        elif missing_artifacts:
            status = "unavailable"
            severity = "error"
        elif offline_status != "complete":
            status = "degraded"
            severity = "warning"

        hint = _dgekt_hint(status=status, offline_status=offline_status)
        return ProviderHealthComponent(
            component="kt",
            display_name="KT / DGEKT",
            mode=settings.kt_engine,
            provider="dgekt",
            configured=configured,
            status=status,
            severity=severity,
            recoverable=True,
            actionable_hint=hint,
            evidence_gaps=(
                _configuration_gaps(
                    provider="dgekt",
                    operation="kt_readiness",
                    missing_fields=missing_fields,
                    hint=hint,
                )
                + _artifact_gaps(
                    provider="dgekt",
                    operation="kt_readiness",
                    missing_artifacts=missing_artifacts,
                    hint=hint,
                    severity="error",
                )
                + offline_gaps
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
    missing_fields: list[str] = []
    missing_artifacts: list[str] = []

    if settings.content_source == "demo":
        if not CONTENT_PATH.is_file():
            missing_artifacts.append("demo teaching content artifact")
    elif settings.content_source == "imported":
        if not settings.content_import_path:
            missing_fields.append("MATHTUTOR_CONTENT_IMPORT_PATH")
        elif not _resolve_project_path(settings.content_import_path).is_file():
            missing_artifacts.append("imported content_import.json")

    if settings.rag_source == "demo":
        if not RAG_PATH.is_file():
            missing_artifacts.append("demo RAG artifact")
    elif settings.rag_source == "imported":
        if not settings.rag_artifact_path:
            missing_fields.append("MATHTUTOR_RAG_ARTIFACT_PATH")
        elif not _resolve_project_path(settings.rag_artifact_path).is_file():
            missing_artifacts.append("imported rag_documents.json")

    configured = not missing_fields and not missing_artifacts
    mode = f"content:{settings.content_source}/rag:{settings.rag_source}"
    status: ProviderHealthStatus = "healthy"
    severity = "info"
    if missing_fields:
        status = "not_configured"
        severity = "warning"
    elif missing_artifacts:
        status = "unavailable"
        severity = "error"
    provider = _content_rag_provider(settings)
    hint = (
        "默认 demo content 与 demo RAG artifact 可运行；当前内容/RAG artifact 只作为教学和解释证据，不覆盖 KT facts。"
        if configured and provider == "demo_artifacts"
        else f"{provider} 可用于学习驾驶舱；当前内容/RAG artifact 只作为教学和解释证据，不覆盖 KT facts。"
        if configured
        else "Content/RAG artifact readiness 存在缺口；补齐导入路径或切回 demo，默认学习流程可继续使用可用本地证据。"
    )
    return ProviderHealthComponent(
        component="content_rag_artifact",
        display_name="Content/RAG artifact",
        mode=mode,
        provider=provider,
        configured=configured,
        status=status,
        severity=severity,
        recoverable=True,
        actionable_hint=hint,
        evidence_gaps=(
            _configuration_gaps(
                provider=provider,
                operation="content_rag_artifact_readiness",
                missing_fields=missing_fields,
                hint=hint,
            )
            + _artifact_gaps(
                provider=provider,
                operation="content_rag_artifact_readiness",
                missing_artifacts=missing_artifacts,
                hint=hint,
                severity="error",
            )
        ),
        last_checked_at=checked_at,
    )


def _learning_context_health(
    settings: MathTutorSettings,
    checked_at: str,
) -> ProviderHealthComponent:
    provider_inputs = [
        f"memory:{settings.memory_provider_mode}",
        f"rag:{settings.rag_provider_mode}",
        f"content:{settings.content_source}",
        f"kt:{settings.kt_engine}",
    ]
    mode = "local_fallback" if provider_inputs == [
        "memory:local_fallback",
        "rag:local_fallback",
        "content:demo",
        "kt:mock",
    ] else "context_evidence_assembly"
    provider = "in_memory_context_layer"
    hint = (
        "LearningContextLayer 使用本地 fallback 证据组装上下文；它只汇总 evidence，不决定 mastery 或 KT facts。"
        if mode == "local_fallback"
        else "LearningContextLayer 会组装当前 Memory/RAG/Content/KT 证据；若上游 provider 或 artifact 降级，只保留 evidence gap，不改写学习事实。"
    )
    return ProviderHealthComponent(
        component="learning_context",
        display_name="LearningContextLayer",
        mode=mode,
        provider=provider,
        configured=True,
        status="healthy",
        severity="info",
        recoverable=True,
        actionable_hint=hint,
        evidence_gaps=[],
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


def _apply_provider_gaps(
    components: list[ProviderHealthComponent],
    provider_gaps: Iterable[Mapping[str, Any]],
) -> list[ProviderHealthComponent]:
    normalized_by_component: dict[str, list[dict[str, Any]]] = {}
    for gap in provider_gaps:
        component = _provider_gap_component(gap)
        normalized = _provider_health_gap(gap)
        normalized_by_component.setdefault(component, []).append(normalized)

    if not normalized_by_component:
        return components

    updated: list[ProviderHealthComponent] = []
    for component in components:
        component_gaps = normalized_by_component.get(component.component, [])
        if not component_gaps:
            updated.append(component)
            continue
        status = _most_severe_status(
            [component.status, *(str(gap["status"]) for gap in component_gaps)]
        )
        severity = _most_severe_severity(
            [component.severity, *(str(gap["severity"]) for gap in component_gaps)]
        )
        primary_gap = component_gaps[0]
        updated.append(
            component.model_copy(
                update={
                    "status": status,
                    "severity": severity,
                    "recoverable": component.recoverable and bool(primary_gap["recoverable"]),
                    "actionable_hint": primary_gap["actionable_hint"],
                    "evidence_gaps": [
                        *component.evidence_gaps,
                        *component_gaps,
                    ],
                }
            )
        )
    return updated


def _provider_health_gap(gap: Mapping[str, Any]) -> dict[str, Any]:
    gap_type = str(gap.get("gap_type") or gap.get("category") or gap.get("code") or "")
    if gap_type not in PROVIDER_EVIDENCE_GAP_TYPES:
        gap_type = "provider_failure"
    presentation = PROVIDER_GAP_HEALTH[gap_type]
    provider = _safe_text(gap.get("provider") or "provider")
    operation = _safe_text(gap.get("operation") or "readiness")
    details = _sanitize_health_value(gap.get("details") or {})
    if not isinstance(details, dict):
        details = {}
    return {
        "gap_type": gap_type,
        "code": gap_type,
        "category": gap_type,
        "provider": provider,
        "operation": operation,
        "stage": _safe_text(gap.get("stage") or "provider_health"),
        "status": presentation["status"],
        "severity": presentation["severity"],
        "recoverable": bool(gap.get("recoverable", True)),
        "reason": presentation["message"],
        "message": presentation["message"],
        "impact": presentation["impact"],
        "actionable_hint": presentation["actionable_hint"],
        "details": {
            "source_gap_type": gap_type,
            **details,
        },
    }


def _provider_gap_component(gap: Mapping[str, Any]) -> str:
    explicit = str(gap.get("health_component") or "")
    if explicit in {"memory", "rag", "kt", "content_rag_artifact", "learning_context"}:
        return explicit
    provider = str(gap.get("provider") or "").lower()
    operation = str(gap.get("operation") or "").lower()
    if "mem0" in provider or "memory" in provider or "memory" in operation:
        return "memory"
    if (
        "viking" in provider
        or "openviking" in provider
        or "rag" in provider
        or "search" in operation
        or "citation" in operation
    ):
        return "rag"
    if "dgekt" in provider or "kt" in provider or "diagnos" in operation:
        return "kt"
    return "learning_context"


def _most_severe_status(statuses: Iterable[str]) -> ProviderHealthStatus:
    order = {
        "healthy": 0,
        "not_configured": 1,
        "degraded": 2,
        "unavailable": 3,
    }
    value = max(statuses, key=lambda status: order.get(status, 0))
    return value if value in order else "healthy"


def _most_severe_severity(severities: Iterable[str]) -> str:
    order = {"info": 0, "warning": 1, "error": 2}
    value = max(severities, key=lambda severity: order.get(severity, 0))
    return value if value in order else "info"


def _sanitize_health_value(value: Any) -> Any:
    if isinstance(value, Mapping):
        sanitized: dict[str, Any] = {}
        for key, item in value.items():
            key_text = str(key)
            if _is_sensitive_health_key(key_text):
                continue
            sanitized[key_text] = _sanitize_health_value(item)
        return sanitized
    if isinstance(value, list):
        return [_sanitize_health_value(item) for item in value]
    if isinstance(value, tuple):
        return [_sanitize_health_value(item) for item in value]
    if isinstance(value, str):
        return _safe_text(value)
    return value


def _is_sensitive_health_key(key: str) -> bool:
    normalized = key.lower().replace("-", "_")
    compact = normalized.replace("_", "")
    if normalized in RAW_PROVIDER_KEYS:
        return True
    if any(token in normalized for token in ("raw_provider", "sdk_response", "provider_debug")):
        return True
    if "embedding" in normalized or "vector" in normalized:
        return True
    return any(
        token in compact
        for token in (
            "apikey",
            "authorization",
            "bearer",
            "credential",
            "secret",
            "token",
            "password",
        )
    )


def _safe_text(value: Any) -> str:
    text = str(value)
    replacements = [
        (r"(?i)(authorization\s*:\s*bearer\s+)\S+", r"\1<redacted>"),
        (r"(?i)(bearer\s+)\S+", r"\1<redacted>"),
        (r"(?i)(api[_-]?key\s*[=:]\s*)\S+", r"\1<redacted>"),
        (r"(?i)(x-api-key\s*[=:]\s*)\S+", r"\1<redacted>"),
        (r"(?i)(credential[s]?\s*[=:]\s*)\S+", r"\1<redacted>"),
        (r"(?i)(secret\s*[=:]\s*)\S+", r"\1<redacted>"),
        (r"(?i)(token\s*[=:]\s*)\S+", r"\1<redacted>"),
        (r"(?i)(/Users/|/var/|/tmp/|/private/|/Volumes/)[^\s\"']+", "<local_path_redacted>"),
        (r"(?i)[A-Z]:\\[^\s\"']+", "<local_path_redacted>"),
    ]
    for pattern, replacement in replacements:
        text = re.sub(pattern, replacement, text)
    return text


def _dgekt_offline_evidence_gaps(
    settings: MathTutorSettings,
) -> tuple[list[dict[str, Any]], str]:
    hint = (
        "DGEKT offline evidence 未配置；在线 partial proxy 可继续解释 prediction，"
        "但不能伪装成 complete offline evidence。"
    )
    if not settings.dgekt_offline_evidence_dir:
        return [
            {
                "gap_type": "missing_artifact",
                "code": "offline_evidence_not_configured",
                "category": "missing_artifact",
                "provider": "dgekt",
                "operation": "kt_readiness",
                "reason": "DGEKT offline evidence 未配置，当前 explanation readiness 为 partial。",
                "message": "DGEKT offline evidence 未配置。",
                "severity": "warning",
                "recoverable": True,
                "actionable_hint": hint,
                "details": {
                    "offline_evidence_status": "partial",
                    "missing_fields": ["MATHTUTOR_DGEKT_OFFLINE_EVIDENCE_DIR"],
                },
            }
        ], "partial"

    offline_dir = _resolve_project_path(settings.dgekt_offline_evidence_dir)
    if not offline_dir.is_dir():
        return _artifact_gaps(
            provider="dgekt",
            operation="kt_readiness",
            missing_artifacts=["DGEKT offline evidence directory"],
            hint=(
                "DGEKT offline evidence 路径不可用；请指向包含 offline explainability "
                "fixture 或正式导出文件的目录。"
            ),
            severity="error",
            details={"offline_evidence_status": "unavailable"},
        ), "unavailable"

    missing_files = [
        f"DGEKT offline evidence file {filename}"
        for filename in DGEKT_OFFLINE_EVIDENCE_FILES
        if not (offline_dir / filename).is_file()
    ]
    if missing_files:
        return _artifact_gaps(
            provider="dgekt",
            operation="kt_readiness",
            missing_artifacts=missing_files,
            hint="DGEKT offline evidence artifact 不完整；请重新导出完整 explainability outputs。",
            severity="error",
            details={"offline_evidence_status": "unavailable"},
        ), "unavailable"
    return [], "complete"


def _dgekt_hint(*, status: ProviderHealthStatus, offline_status: str) -> str:
    if status == "healthy":
        return "DGEKT 已显式启用，checkpoint、dataset、KC routes、canonical mapping 与 offline evidence 基础 artifact 均可诊断。"
    if status == "degraded" and offline_status == "partial":
        return (
            "DGEKT 核心配置可诊断，但 offline evidence 未配置；当前只能视为 partial readiness，"
            "不能伪装成 complete offline evidence。"
        )
    if status == "not_configured":
        return "DGEKT 已显式启用，但缺少必要配置；补齐 env 或切回默认 mock KT。"
    return "DGEKT readiness 路径不可用或 artifact 不完整；请修复本地 artifact 后再用于正式试用。"


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


def _artifact_gaps(
    *,
    provider: str,
    operation: str,
    missing_artifacts: list[str],
    hint: str,
    severity: str,
    details: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    if not missing_artifacts:
        return []
    return [
        {
            "gap_type": "missing_artifact",
            "code": "missing_artifact",
            "category": "missing_artifact",
            "provider": provider,
            "operation": operation,
            "reason": f"{provider} readiness 缺少或无法访问必要 artifact。",
            "message": f"{provider} readiness artifact 不完整。",
            "severity": severity,
            "recoverable": True,
            "actionable_hint": hint,
            "details": {
                "missing_artifacts": missing_artifacts,
                **(details or {}),
            },
        }
    ]


def _content_rag_provider(settings: MathTutorSettings) -> str:
    if settings.content_source == "demo" and settings.rag_source == "demo":
        return "demo_artifacts"
    paths = [settings.content_import_path, settings.rag_artifact_path]
    if any("xes3g5m_fixture" in path for path in paths if path):
        return "fixture_artifacts"
    if settings.content_source == "imported" or settings.rag_source == "imported":
        return "imported_artifacts"
    return "mixed_artifacts"


def _resolve_project_path(value: str | Path) -> Path:
    path = Path(value).expanduser()
    if path.is_absolute() or path.exists():
        return path
    return PROJECT_ROOT / path


def _summary(status: ProviderHealthStatus) -> str:
    return {
        "healthy": "默认本地 fallback / mock / demo provider 状态可运行。",
        "degraded": "部分 provider 未配置或处于降级状态，默认学习流程仍可继续。",
        "unavailable": "存在不可用 provider，请先查看组件恢复建议。",
        "not_configured": "provider 尚未配置，请查看组件恢复建议。",
    }[status]
