from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


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


@lru_cache
def get_settings() -> MathTutorSettings:
    return MathTutorSettings()
