from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Iterable

from ..core.config import MathTutorSettings, get_settings
from ..provider_health import build_provider_health
from ..schemas.provider_health import ProviderHealthComponent, ProviderHealthResponse
from ..schemas.readiness import (
    ChecklistItemStatus,
    TrialChecklistItem,
    TrialComponentStatus,
    TrialProbeSummary,
    TrialReadinessComponent,
    TrialReadinessReport,
    TrialReadinessStatus,
)
from ..storage.sqlite_store import SqliteLearningStore, get_learning_store
from .probes import latest_probe_summaries


def build_trial_readiness_report(
    *,
    settings: MathTutorSettings | None = None,
    provider_health: ProviderHealthResponse | None = None,
    provider_gaps: Iterable[dict[str, object]] | None = None,
    store: SqliteLearningStore | None = None,
    probe_summaries: list[TrialProbeSummary] | None = None,
) -> TrialReadinessReport:
    """Aggregate a read-only Trial Readiness Gate report.

    This function must never write progress, KT/DGEKT facts, memory, RAG,
    active context, or TeachingTrace learning decisions.
    """
    active = settings or get_settings()
    checked_at = datetime.now(UTC).isoformat()
    health = provider_health or build_provider_health(
        settings=active,
        provider_gaps=provider_gaps,
    )
    learning_store = store or get_learning_store(active)
    store_health = learning_store.health_check()
    probes = probe_summaries if probe_summaries is not None else latest_probe_summaries(learning_store)
    feedback = learning_store.list_trial_feedback(limit=10)

    components = [
        _provider_configuration_component(health, checked_at),
        _artifact_readiness_component(health, checked_at),
        _persistence_component(store_health, checked_at),
        _runtime_governance_component(checked_at),
        _fallback_safety_component(active, health, checked_at),
        _probe_component(probes, active, checked_at),
        _memory_control_component(store_health, checked_at),
    ]
    artifact_summaries = _artifact_detail_components(health, active, checked_at)
    checklist = _build_checklist(components, artifact_summaries, probes, feedback)
    residual_risks = _residual_risks(components, artifact_summaries, probes, feedback, active)

    overall = _overall_status(components)
    # Default local fallback can be demo-runnable while internal trial remains not ready.
    demo_runnable = _demo_runnable(active, health, store_health)
    internal_trial_ready = overall == "ready" and _human_feedback_allows_ready(feedback)
    if _is_default_fallback(active) and not _has_real_provider_evidence(active, probes):
        # Never auto-promote pure local fallback to trial ready — even when
        # demo components themselves look healthy/degraded.
        overall = "not_ready"
        internal_trial_ready = False
        residual_risks = _unique(
            residual_risks
            + ["默认 local fallback 可运行，但不能自动等同于内部试用 ready。"]
        )

    summary = _summary(
        status=overall,
        demo_runnable=demo_runnable,
        internal_trial_ready=internal_trial_ready,
    )
    return TrialReadinessReport(
        status=overall,
        summary=summary,
        generated_at=checked_at,
        demo_runnable=demo_runnable,
        internal_trial_ready=internal_trial_ready,
        fallback_is_not_trial_ready=True,
        components=components,
        probe_summaries=probes,
        artifact_summaries=artifact_summaries,
        checklist=checklist,
        recent_feedback=feedback,
        residual_risks=residual_risks,
        human_decision_required=True,
    )


def _provider_configuration_component(
    health: ProviderHealthResponse,
    checked_at: str,
) -> TrialReadinessComponent:
    interesting = [
        item
        for item in health.components
        if item.component in {"memory", "rag", "kt", "learning_context"}
    ]
    statuses = [item.status for item in interesting]
    if any(status in {"unavailable", "not_configured"} for status in statuses):
        status: TrialComponentStatus = "degraded"
        # live missing config is degraded for trial, not a hard crash of local demo
        if any(
            item.mode in {"live_provider", "dgekt"} and item.status == "not_configured"
            for item in interesting
        ):
            status = "degraded"
        reason = "部分 provider 配置缺失或不可用。"
        hint = "补齐显式 opt-in provider 配置，或保持 local_fallback 仅用于 demo。"
    elif any(status == "degraded" for status in statuses):
        status = "degraded"
        reason = "provider readiness 存在可恢复降级。"
        hint = "查看 Provider Health 中的 actionable hint，不要把故障写成 mastery。"
    else:
        status = "ready"
        reason = "provider configuration 诊断面可运行。"
        hint = "配置面就绪不等于 live 可达；内部试用仍需人工复核 probe 与真实依赖。"
    return TrialReadinessComponent(
        component="provider_configuration",
        display_name="Provider 配置",
        status=status,
        reason=reason,
        actionable_hint=hint,
        details={
            "provider_health_status": health.status,
            "components": [
                {
                    "component": item.component,
                    "mode": item.mode,
                    "provider": item.provider,
                    "status": item.status,
                }
                for item in interesting
            ],
        },
    )


def _artifact_readiness_component(
    health: ProviderHealthResponse,
    checked_at: str,
) -> TrialReadinessComponent:
    artifact = _find_component(health, "content_rag_artifact")
    kt = _find_component(health, "kt")
    if artifact is None:
        return TrialReadinessComponent(
            component="artifact_readiness",
            display_name="Artifact Readiness",
            status="not_ready",
            reason="缺少 content/RAG artifact readiness 信号。",
            actionable_hint="确认 Provider Health 的 content_rag_artifact 组件可用。",
            details={},
        )
    # Default demo artifacts are runnable but not internal-trial "real evidence ready".
    if artifact.provider == "demo_artifacts" and (kt is None or kt.provider == "mock"):
        return TrialReadinessComponent(
            component="artifact_readiness",
            display_name="Artifact Readiness",
            status="degraded",
            reason="当前仅有 demo/mock 数学证据，不足以证明真实内部试用 artifact 就绪。",
            actionable_hint="显式配置 DGEKT checkpoint/offline evidence 与 imported content/RAG artifact 后再评估 ready。",
            details={
                "content_rag_provider": artifact.provider,
                "content_rag_status": artifact.status,
                "kt_provider": kt.provider if kt else "unknown",
                "kt_status": kt.status if kt else "unknown",
                "evidence_class": "demo_or_mock",
            },
        )
    mapped = _map_provider_status(artifact.status)
    if kt and kt.status in {"not_configured", "unavailable"}:
        mapped = "not_ready" if kt.status == "unavailable" else "degraded"
    elif kt and kt.status == "degraded" and mapped == "ready":
        mapped = "degraded"
    return TrialReadinessComponent(
        component="artifact_readiness",
        display_name="Artifact Readiness",
        status=mapped,
        reason="内容 / DGEKT artifact readiness 已汇总（不含本地路径与模型载荷）。",
        actionable_hint=artifact.actionable_hint,
        details={
            "content_rag_provider": artifact.provider,
            "content_rag_status": artifact.status,
            "kt_provider": kt.provider if kt else "unknown",
            "kt_status": kt.status if kt else "unknown",
        },
    )


def _persistence_component(store_health: dict[str, Any], checked_at: str) -> TrialReadinessComponent:
    if not store_health.get("available"):
        return TrialReadinessComponent(
            component="persistence",
            display_name="持久化恢复",
            status="not_ready",
            reason=str(store_health.get("reason") or "本地持久化不可用。"),
            actionable_hint="检查 MATHTUTOR_DB_URL 与 data/local SQLite 可写性；失败时不要伪造 progress。",
            details={"backend": store_health.get("backend"), "error_category": store_health.get("error_category")},
        )
    return TrialReadinessComponent(
        component="persistence",
        display_name="持久化恢复",
        status="ready",
        reason="本地 SQLite 持久化可读写，可恢复 progress / TeachingTrace 摘要 / 记忆控制状态。",
        actionable_hint="用同一学生完成答题后重启进程，验证 progress 与 trace 摘要恢复。",
        details={
            "backend": store_health.get("backend"),
            "schema_version": store_health.get("schema_version"),
            "progress_count": store_health.get("progress_count"),
            "trace_count": store_health.get("trace_count"),
            "memory_count": store_health.get("memory_count"),
            "path_category": store_health.get("path_category"),
        },
    )


def _runtime_governance_component(checked_at: str) -> TrialReadinessComponent:
    return TrialReadinessComponent(
        component="runtime_context_governance",
        display_name="Runtime Context Governance",
        status="ready",
        reason="V1.10 Context Governance 边界已接入：只审计上下文，不改写 KT/DGEKT 事实。",
        actionable_hint="专家侧继续检查 budget / evidence priority / tool mount / response context 脱敏摘要。",
        details={
            "state_reference_only": True,
            "writes_learning_facts": False,
        },
    )


def _fallback_safety_component(
    settings: MathTutorSettings,
    health: ProviderHealthResponse,
    checked_at: str,
) -> TrialReadinessComponent:
    default_fallback = _is_default_fallback(settings)
    if default_fallback and health.status in {"healthy", "degraded"}:
        return TrialReadinessComponent(
            component="default_fallback_safety",
            display_name="默认 Fallback 安全",
            status="ready",
            reason="默认 local fallback / mock / demo 可运行，且不会被自动提升为内部试用 ready。",
            actionable_hint="保持真实 provider、checkpoint、canary 为显式 opt-in；凭据与数据不进 Git。",
            details={
                "memory_mode": settings.memory_provider_mode,
                "rag_mode": settings.rag_provider_mode,
                "kt_engine": settings.kt_engine,
                "content_source": settings.content_source,
                "rag_source": settings.rag_source,
                "auto_promote_to_trial_ready": False,
            },
        )
    if not default_fallback:
        return TrialReadinessComponent(
            component="default_fallback_safety",
            display_name="默认 Fallback 安全",
            status="degraded",
            reason="当前启用了非默认 live/imported/dgekt 路径；请确认均为显式 opt-in。",
            actionable_hint="确认 env 为受控配置，并在 Gate 中分别检查 probe 与 artifact 证据。",
            details={
                "memory_mode": settings.memory_provider_mode,
                "rag_mode": settings.rag_provider_mode,
                "kt_engine": settings.kt_engine,
            },
        )
    return TrialReadinessComponent(
        component="default_fallback_safety",
        display_name="默认 Fallback 安全",
        status="not_ready",
        reason="默认 fallback 诊断异常。",
        actionable_hint="检查 Provider Health 与本地 demo artifact 是否可读。",
        details={},
    )


def _probe_component(
    probes: list[TrialProbeSummary],
    settings: MathTutorSettings,
    checked_at: str,
) -> TrialReadinessComponent:
    if not settings.enable_provider_canary_probe:
        return TrialReadinessComponent(
            component="provider_canary_probe",
            display_name="Provider Canary Probe",
            status="skipped",
            reason="canary probe 默认关闭，已安全跳过真实外部访问。",
            actionable_hint="仅在运维窗口设置 MATHTUTOR_ENABLE_PROVIDER_CANARY_PROBE=true 并提供隔离 canary 条件。",
            details={"recent_probe_count": len(probes)},
        )
    if not probes:
        return TrialReadinessComponent(
            component="provider_canary_probe",
            display_name="Provider Canary Probe",
            status="degraded",
            reason="已启用 canary probe，但尚无规范化 probe 结果。",
            actionable_hint="通过专家侧手动触发一次 memory/rag canary probe。",
            details={},
        )
    if any(item.status == "not_ready" for item in probes if not item.skipped):
        return TrialReadinessComponent(
            component="provider_canary_probe",
            display_name="Provider Canary Probe",
            status="not_ready",
            reason="最近 canary probe 存在 not_ready 结果。",
            actionable_hint="根据脱敏 reason 修复鉴权/配置/预算问题后重试。",
            details={"recent_probe_count": len(probes)},
        )
    if any(item.status == "degraded" for item in probes if not item.skipped):
        return TrialReadinessComponent(
            component="provider_canary_probe",
            display_name="Provider Canary Probe",
            status="degraded",
            reason="最近 canary probe 存在可恢复降级。",
            actionable_hint="复核 provider 可达性与预算；不要把 probe 结果写入学习事实。",
            details={"recent_probe_count": len(probes)},
        )
    return TrialReadinessComponent(
        component="provider_canary_probe",
        display_name="Provider Canary Probe",
        status="ready",
        reason="最近 canary probe 结果可用。",
        actionable_hint="保留 probe 审计记录，人工决定是否继续邀请试用用户。",
        details={"recent_probe_count": len(probes)},
    )


def _memory_control_component(
    store_health: dict[str, Any],
    checked_at: str,
) -> TrialReadinessComponent:
    if not store_health.get("available"):
        return TrialReadinessComponent(
            component="memory_control_persistence",
            display_name="记忆控制持久化",
            status="not_ready",
            reason="记忆控制状态无法持久化恢复。",
            actionable_hint="修复 SQLite 持久化后，再验证 disable/delete 跨重启生效。",
            details={},
        )
    return TrialReadinessComponent(
        component="memory_control_persistence",
        display_name="记忆控制持久化",
        status="ready",
        reason="学生记忆 enable/disable/delete 状态可持久化，且不改写 KT facts。",
        actionable_hint="禁用后重启确认 context 排除；删除后重启确认列表与详情均不可见。",
        details={"memory_count": store_health.get("memory_count")},
    )


def _artifact_detail_components(
    health: ProviderHealthResponse,
    settings: MathTutorSettings,
    checked_at: str,
) -> list[TrialReadinessComponent]:
    kt = _find_component(health, "kt")
    content = _find_component(health, "content_rag_artifact")
    details: list[TrialReadinessComponent] = []

    if settings.kt_engine == "mock":
        details.append(
            TrialReadinessComponent(
                component="dgekt_checkpoint",
                display_name="DGEKT Checkpoint",
                status="degraded",
                reason="默认 mock KT，未启用真实 DGEKT checkpoint。",
                actionable_hint="仅在显式设置 MATHTUTOR_KT_ENGINE=dgekt 并提供本地 checkpoint 后评估真实证据。",
                details={"configured": False, "evidence_class": "mock"},
            )
        )
        details.append(
            TrialReadinessComponent(
                component="dgekt_dataset_qmatrix",
                display_name="DGEKT Dataset / Q-matrix",
                status="degraded",
                reason="默认 mock 路径不加载真实 dataset / Q-matrix。",
                actionable_hint="显式配置 dataset_dir 与 q_matrix 路径（Git 外）后再验证。",
                details={"configured": False, "evidence_class": "mock"},
            )
        )
        details.append(
            TrialReadinessComponent(
                component="dgekt_offline_evidence",
                display_name="DGEKT Offline Evidence",
                status="degraded",
                reason="默认未挂载真实 offline attribution evidence。",
                actionable_hint="可使用仓库内 offline_evidence_fixture 做受控验证，或配置完整 offline evidence 目录。",
                details={"configured": bool(settings.dgekt_offline_evidence_dir), "evidence_class": "optional_fixture"},
            )
        )
    else:
        details.append(
            TrialReadinessComponent(
                component="dgekt_checkpoint",
                display_name="DGEKT Checkpoint",
                status=_map_provider_status(kt.status if kt else "not_configured"),
                reason="DGEKT checkpoint readiness 已按配置/存在性诊断（不读模型载荷）。",
                actionable_hint=kt.actionable_hint if kt else "补齐 DGEKT 配置。",
                details={"kt_status": kt.status if kt else "not_configured", "path_leaked": False},
            )
        )
        details.append(
            TrialReadinessComponent(
                component="dgekt_dataset_qmatrix",
                display_name="DGEKT Dataset / Q-matrix",
                status=_map_provider_status(kt.status if kt else "not_configured"),
                reason="Dataset / Q-matrix readiness 已纳入 KT 诊断。",
                actionable_hint="只报告类别与状态，不输出绝对路径。",
                details={"path_leaked": False},
            )
        )
        offline_status: TrialComponentStatus = "degraded"
        if kt and kt.status == "healthy":
            offline_status = "ready"
        elif kt and kt.status in {"unavailable", "not_configured"}:
            offline_status = _map_provider_status(kt.status)
        details.append(
            TrialReadinessComponent(
                component="dgekt_offline_evidence",
                display_name="DGEKT Offline Evidence",
                status=offline_status,
                reason="Offline evidence 仅作解释证据，不覆盖 prediction facts。",
                actionable_hint=kt.actionable_hint if kt else "配置 offline evidence 目录。",
                details={"path_leaked": False},
            )
        )

    if content and content.provider == "demo_artifacts":
        details.append(
            TrialReadinessComponent(
                component="imported_content",
                display_name="Imported Content",
                status="degraded",
                reason="当前使用 demo teaching content，不是 imported 完整内容。",
                actionable_hint="显式设置 content_source=imported 并提供 content_import artifact。",
                details={"provider": content.provider, "status": content.status},
            )
        )
        details.append(
            TrialReadinessComponent(
                component="imported_rag_artifact",
                display_name="Imported RAG Artifact",
                status="degraded",
                reason="当前使用 demo RAG artifact。",
                actionable_hint="显式设置 rag_source=imported 并提供 rag_documents artifact。",
                details={"provider": content.provider, "status": content.status},
            )
        )
    else:
        mapped = _map_provider_status(content.status if content else "not_configured")
        details.append(
            TrialReadinessComponent(
                component="imported_content",
                display_name="Imported Content",
                status=mapped,
                reason="Imported content readiness 已诊断（无路径/载荷）。",
                actionable_hint=content.actionable_hint if content else "配置 imported content。",
                details={"provider": content.provider if content else "unknown"},
            )
        )
        details.append(
            TrialReadinessComponent(
                component="imported_rag_artifact",
                display_name="Imported RAG Artifact",
                status=mapped,
                reason="Imported RAG artifact readiness 已诊断（无路径/载荷）。",
                actionable_hint=content.actionable_hint if content else "配置 imported RAG。",
                details={"provider": content.provider if content else "unknown"},
            )
        )
    return details


def _build_checklist(
    components: list[TrialReadinessComponent],
    artifacts: list[TrialReadinessComponent],
    probes: list[TrialProbeSummary],
    feedback: list[Any],
) -> list[TrialChecklistItem]:
    by_id = {item.component: item for item in components}
    items = [
        _checklist_from_component(
            "provider_artifact",
            "Provider / Artifact 就绪",
            by_id.get("provider_configuration"),
            by_id.get("artifact_readiness"),
        ),
        _checklist_from_component(
            "persistence",
            "持久化连续学习恢复",
            by_id.get("persistence"),
        ),
        _checklist_from_component(
            "memory_control",
            "学生记忆控制跨重启",
            by_id.get("memory_control_persistence"),
        ),
        _checklist_from_component(
            "fallback_safety",
            "默认 Fallback 安全边界",
            by_id.get("default_fallback_safety"),
        ),
        _checklist_from_component(
            "runtime_governance",
            "Runtime Context Governance",
            by_id.get("runtime_context_governance"),
        ),
        TrialChecklistItem(
            item_id="human_decision",
            title="人工试用结论",
            status="pending_human" if not feedback else _feedback_checklist_status(feedback),
            summary=(
                "尚未记录人工 ready/hold/not_ready 结论。"
                if not feedback
                else f"最近人工结论：{feedback[0].decision}。"
            ),
            actionable_hint="运营者完成连续学习复核后写入试用反馈；系统不会自动批准试用。",
        ),
    ]
    if artifacts:
        blocking = [item for item in artifacts if item.status == "not_ready"]
        degraded = [item for item in artifacts if item.status == "degraded"]
        if blocking:
            status: ChecklistItemStatus = "blocking"
            summary = f"{len(blocking)} 项真实 artifact 阻塞试用。"
        elif degraded:
            status = "degraded"
            summary = f"{len(degraded)} 项 artifact 仍为 demo/partial。"
        else:
            status = "met"
            summary = "真实 artifact 信号均可用。"
        items.insert(
            1,
            TrialChecklistItem(
                item_id="real_artifacts",
                title="真实 DGEKT / 内容 Artifact",
                status=status,
                summary=summary,
                actionable_hint="区分 demo fallback 与真实 evidence；输出不得含绝对路径。",
            ),
        )
    if probes is not None:
        skipped = all(item.skipped for item in probes) if probes else True
        items.append(
            TrialChecklistItem(
                item_id="canary_probe",
                title="受控 Canary Probe",
                status="pending_human" if skipped else (
                    "blocking"
                    if any(item.status == "not_ready" for item in probes)
                    else "degraded"
                    if any(item.status == "degraded" for item in probes)
                    else "met"
                ),
                summary=(
                    "默认跳过真实 probe。"
                    if skipped
                    else f"已记录 {len(probes)} 条 probe 摘要。"
                ),
                actionable_hint="无凭据时保持跳过；有隔离 canary 时手动执行并仅保留脱敏摘要。",
            )
        )
    return items


def _checklist_from_component(
    item_id: str,
    title: str,
    *components: TrialReadinessComponent | None,
) -> TrialChecklistItem:
    present = [item for item in components if item is not None]
    if not present:
        return TrialChecklistItem(
            item_id=item_id,
            title=title,
            status="blocking",
            summary="缺少 readiness 信号。",
            actionable_hint="先完成对应 Gate 组件实现。",
        )
    if any(item.status == "not_ready" for item in present):
        status: ChecklistItemStatus = "blocking"
    elif any(item.status in {"degraded", "skipped"} for item in present):
        status = "degraded"
    else:
        status = "met"
    summary = "；".join(item.reason for item in present)
    hint = present[0].actionable_hint
    return TrialChecklistItem(
        item_id=item_id,
        title=title,
        status=status,
        summary=summary,
        actionable_hint=hint,
    )


def _feedback_checklist_status(feedback: list[Any]) -> ChecklistItemStatus:
    decision = getattr(feedback[0], "decision", None)
    if decision == "ready":
        return "met"
    if decision == "hold":
        return "pending_human"
    return "blocking"


def _residual_risks(
    components: list[TrialReadinessComponent],
    artifacts: list[TrialReadinessComponent],
    probes: list[TrialProbeSummary],
    feedback: list[Any],
    settings: MathTutorSettings,
) -> list[str]:
    risks: list[str] = []
    for item in components + artifacts:
        if item.status in {"degraded", "not_ready", "skipped"}:
            risks.append(f"{item.display_name}：{item.reason}")
    if not feedback:
        risks.append("缺少人工试用结论（ready/hold/not_ready）。")
    if _is_default_fallback(settings):
        risks.append("当前默认路径未证明真实 Mem0/Viking/DGEKT 生产依赖。")
    if not probes or all(item.skipped for item in probes):
        risks.append("尚未执行或全部跳过 canary probe。")
    return _unique(risks)


def _overall_status(components: list[TrialReadinessComponent]) -> TrialReadinessStatus:
    statuses = [item.status for item in components if item.status != "skipped"]
    if any(status == "not_ready" for status in statuses):
        return "not_ready"
    if any(status == "degraded" for status in statuses):
        return "degraded"
    if not statuses:
        return "not_ready"
    return "ready"


def _summary(
    *,
    status: TrialReadinessStatus,
    demo_runnable: bool,
    internal_trial_ready: bool,
) -> str:
    demo_text = "默认 demo/fallback 可运行" if demo_runnable else "默认 demo/fallback 异常"
    trial_text = "内部试用 ready" if internal_trial_ready else "内部试用未 ready"
    if status == "ready":
        return f"Trial Readiness：ready。{demo_text}；{trial_text}。最终仍需人工确认。"
    if status == "degraded":
        return f"Trial Readiness：degraded。{demo_text}；{trial_text}。请按组件 hint 恢复后再人工决定。"
    return f"Trial Readiness：not_ready。{demo_text}；{trial_text}。在扩大试用前先关闭阻塞项。"


def _demo_runnable(
    settings: MathTutorSettings,
    health: ProviderHealthResponse,
    store_health: dict[str, Any],
) -> bool:
    if not store_health.get("available"):
        return False
    if not _is_default_fallback(settings):
        return health.status in {"healthy", "degraded"}
    return health.status in {"healthy", "degraded"}


def _is_default_fallback(settings: MathTutorSettings) -> bool:
    return (
        settings.memory_provider_mode == "local_fallback"
        and settings.rag_provider_mode == "local_fallback"
        and settings.kt_engine == "mock"
        and settings.content_source == "demo"
        and settings.rag_source == "demo"
    )


def _has_real_provider_evidence(
    settings: MathTutorSettings,
    probes: list[TrialProbeSummary],
) -> bool:
    if settings.memory_provider_mode == "live_provider" or settings.rag_provider_mode == "live_provider":
        return any(not item.skipped and item.status in {"ready", "degraded"} for item in probes)
    if settings.kt_engine == "dgekt":
        return True
    if settings.content_source == "imported" or settings.rag_source == "imported":
        return True
    return False


def _human_feedback_allows_ready(feedback: list[Any]) -> bool:
    return bool(feedback) and getattr(feedback[0], "decision", None) == "ready"


def _find_component(
    health: ProviderHealthResponse,
    name: str,
) -> ProviderHealthComponent | None:
    for item in health.components:
        if item.component == name:
            return item
    return None


def _map_provider_status(status: str) -> TrialComponentStatus:
    if status == "healthy":
        return "ready"
    if status == "degraded":
        return "degraded"
    if status == "not_configured":
        return "degraded"
    return "not_ready"


def _unique(items: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for item in items:
        if item in seen:
            continue
        seen.add(item)
        result.append(item)
    return result
