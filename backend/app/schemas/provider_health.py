from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


ProviderHealthStatus = Literal[
    "healthy",
    "degraded",
    "unavailable",
    "not_configured",
]
ProviderHealthSeverity = Literal["info", "warning", "error"]


class ProviderHealthComponent(BaseModel):
    model_config = ConfigDict(extra="forbid")

    component: str
    display_name: str
    mode: str
    provider: str
    configured: bool
    status: ProviderHealthStatus
    severity: ProviderHealthSeverity
    recoverable: bool
    actionable_hint: str
    evidence_gaps: list[dict[str, object]] = Field(default_factory=list)
    last_checked_at: str


class ProviderHealthResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: ProviderHealthStatus
    summary: str
    generated_at: str
    components: list[ProviderHealthComponent]
