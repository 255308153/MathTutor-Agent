from __future__ import annotations

from ..core.config import MathTutorSettings, get_settings
from .dgekt_engine import DGEKTStateEngine
from .engine import KTStateEngine
from .mock_engine import MockKTStateEngine


def create_kt_engine(settings: MathTutorSettings | None = None) -> KTStateEngine:
    active_settings = settings or get_settings()
    if active_settings.kt_engine == "mock":
        return MockKTStateEngine()
    if active_settings.kt_engine == "dgekt":
        return DGEKTStateEngine(
            dataset=active_settings.dgekt_dataset,
            checkpoint_path=active_settings.dgekt_checkpoint_path,
            checkpoint_id=active_settings.dgekt_checkpoint_id,
            dataset_dir=active_settings.dgekt_dataset_dir,
            kc_routes_path=active_settings.dgekt_kc_routes_path,
            offline_evidence_dir=active_settings.dgekt_offline_evidence_dir,
            canonical_mapping_path=active_settings.dgekt_canonical_mapping_path,
        )
    raise ValueError(f"Unsupported KT engine: {active_settings.kt_engine}")
