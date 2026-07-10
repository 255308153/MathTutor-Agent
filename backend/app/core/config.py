from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


ProviderMode = Literal["local_fallback", "fake_provider", "live_provider"]
RAGLiveProvider = Literal["vikingdb", "openviking"]


class MathTutorSettings(BaseSettings):
    """Runtime settings for MathTutor.

    Defaults deliberately keep V1.1 runnable without any DGEKT files.
    """

    model_config = SettingsConfigDict(env_prefix="MATHTUTOR_", env_file=".env", extra="ignore")

    env: str = "development"
    db_url: str = "sqlite:///./data/local/mathtutor.sqlite"
    vector_backend: str = "chroma"
    llm_provider: str = "mock"
    llm_model: str = ""
    openai_api_key: str = ""

    memory_provider_mode: ProviderMode = "local_fallback"
    rag_provider_mode: ProviderMode = "local_fallback"
    mem0_api_key: str = ""
    vikingdb_api_key: str = ""
    openviking_api_key: str = ""
    rag_live_provider: RAGLiveProvider = "vikingdb"
    rag_provider_endpoint: str = ""
    rag_provider_collection: str = ""
    rag_provider_namespace: str = ""
    rag_provider_search_path: str = "/search"
    rag_provider_supports_metadata_filter: bool = True
    rag_provider_timeout_seconds: float = 5.0
    run_mem0_live_smoke: bool = False
    run_viking_rag_smoke: bool = False
    viking_rag_smoke_query: str = ""

    assist2017_dataset_mode: Literal["demo", "fixture", "full"] = "demo"
    assist2017_full_source_rows_path: str = ""
    assist2017_full_q_matrix_path: str = ""
    assist2017_full_artifact_dir: str = ""

    content_source: Literal["demo", "imported"] = "demo"
    content_import_path: str = ""
    rag_source: Literal["demo", "imported"] = "demo"
    rag_artifact_path: str = ""

    kt_engine: Literal["mock", "dgekt"] = "mock"
    dgekt_dataset: str = "assist2017"
    dgekt_checkpoint_path: str = ""
    dgekt_checkpoint_id: str = ""
    dgekt_dataset_dir: str = ""
    dgekt_q_matrix_path: str = ""
    dgekt_offline_evidence_dir: str = ""
    dgekt_canonical_mapping_path: str = ""

    # V1.11 Trial Readiness / canary probes (all default off for safety)
    enable_provider_canary_probe: bool = False
    persistence_backend: Literal["sqlite", "memory"] = "sqlite"


@lru_cache
def get_settings() -> MathTutorSettings:
    return MathTutorSettings()
