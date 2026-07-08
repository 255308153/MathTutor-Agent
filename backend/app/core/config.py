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

    kt_engine: Literal["mock", "dgekt"] = "mock"
    dgekt_dataset: str = "assist2017"
    dgekt_checkpoint_path: str = ""
    dgekt_dataset_dir: str = ""
    dgekt_q_matrix_path: str = ""


@lru_cache
def get_settings() -> MathTutorSettings:
    return MathTutorSettings()
