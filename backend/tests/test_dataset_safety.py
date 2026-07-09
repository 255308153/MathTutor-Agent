from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from backend.app.core.config import MathTutorSettings
from backend.app.importing.dataset_safety import (
    find_banned_tracked_paths,
    tracked_paths_from_git,
)


ROOT = Path(__file__).resolve().parents[2]


def test_default_settings_keep_demo_mock_and_no_full_paths() -> None:
    settings = MathTutorSettings()

    assert settings.assist2017_dataset_mode == "demo"
    assert settings.content_source == "demo"
    assert settings.rag_source == "demo"
    assert settings.kt_engine == "mock"
    assert settings.assist2017_full_source_rows_path == ""
    assert settings.assist2017_full_q_matrix_path == ""
    assert settings.assist2017_full_artifact_dir == ""
    assert settings.dgekt_checkpoint_path == ""
    assert settings.dgekt_checkpoint_id == ""
    assert settings.dgekt_offline_evidence_dir == ""
    assert settings.dgekt_canonical_mapping_path == ""


def test_artifact_cli_fixture_mode_uses_committed_small_fixture(
    tmp_path: Path,
) -> None:
    output_dir = tmp_path / "fixture-output"

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "backend.app.importing.build_assist2017_artifacts",
            "--dataset-mode",
            "fixture",
            "--output-dir",
            str(output_dir),
            "--generated-at",
            "2026-07-09T00:00:00+00:00",
        ],
        cwd=ROOT,
        check=True,
        text=True,
        capture_output=True,
    )

    payload = json.loads(result.stdout)
    assert payload["dataset_mode"] == "fixture"
    assert payload["source_rows"].endswith("data/import/assist2017_source.fixture.csv")
    assert payload["q_matrix"].endswith("data/mapping/assist2017_q_matrix.fixture.csv")
    assert payload["coverage_summary"]["mapping"]["mapped_question_count"] == 3


def test_artifact_cli_full_mode_requires_explicit_paths(tmp_path: Path) -> None:
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "backend.app.importing.build_assist2017_artifacts",
            "--dataset-mode",
            "full",
            "--output-dir",
            str(tmp_path / "full-output"),
        ],
        cwd=ROOT,
        check=False,
        text=True,
        capture_output=True,
    )

    assert result.returncode == 2
    assert "--dataset-mode full 必须显式设置 --source-rows 和 --q-matrix" in result.stderr


def test_repository_safety_allows_only_committed_fixture_assets() -> None:
    fixture_paths = [
        ".env.example",
        "data/import/assist2017_source.fixture.csv",
        "data/mapping/assist2017_q_matrix.fixture.csv",
        "data/mapping/assist2017_canonical_mapping.fixture.json",
        "data/imported/assist2017_fixture/coverage_report.json",
        "data/dgekt/offline_evidence_fixture/diagnosis_cases.json",
        "data/dgekt/offline_evidence_fixture/attribution_paths.csv",
        "data/dgekt/offline_evidence_fixture/key_history.csv",
        "data/dgekt/offline_evidence_fixture/path_ablation.csv",
        "data/dgekt/offline_evidence_fixture/weak_concepts.csv",
    ]

    assert find_banned_tracked_paths(fixture_paths) == []


def test_repository_safety_flags_raw_models_cache_and_full_generated_outputs() -> None:
    violations = find_banned_tracked_paths(
        [
            ".env",
            ".env.production",
            "secrets/provider.env",
            "config/provider_credentials.json",
            "config/openviking_api_key.txt",
            "data/raw/assist2017/assist2017_pid_train.csv",
            "data/import/assist2017/source_rows.csv",
            "data/import/full/content_import.json",
            "data/import/assist2017/assist2017_pid_test.csv",
            "data/provider_cache/mem0/search.json",
            "data/generated_vector_indexes/openviking/index.faiss",
            "data/vector_indexes/chroma/collection.sqlite",
            "data/imported/assist2017_full/content_import.json",
            "data/dgekt/full_outputs/diagnosis_cases.json",
            "data/dgekt/full_outputs/attribution_paths.csv",
            "data/dgekt/full_outputs/key_history.csv",
            "data/dgekt/full_outputs/path_ablation.csv",
            "data/dgekt/full_outputs/weak_concepts.csv",
            "research/explainability/weak_concept_hit.csv",
            "provider_caches/vikingdb/raw_response.json",
            "vector_indexes/demo/index.hnsw",
            "checkpoints/save2017model.pkl",
            "frontend/dist/index.html",
            "backend/.pytest_cache/v/cache/nodeids",
        ]
    )

    assert {violation.path for violation in violations} == {
        ".env",
        ".env.production",
        "secrets/provider.env",
        "config/provider_credentials.json",
        "config/openviking_api_key.txt",
        "data/raw/assist2017/assist2017_pid_train.csv",
        "data/import/assist2017/source_rows.csv",
        "data/import/full/content_import.json",
        "data/import/assist2017/assist2017_pid_test.csv",
        "data/provider_cache/mem0/search.json",
        "data/generated_vector_indexes/openviking/index.faiss",
        "data/vector_indexes/chroma/collection.sqlite",
        "data/imported/assist2017_full/content_import.json",
        "data/dgekt/full_outputs/diagnosis_cases.json",
        "data/dgekt/full_outputs/attribution_paths.csv",
        "data/dgekt/full_outputs/key_history.csv",
        "data/dgekt/full_outputs/path_ablation.csv",
        "data/dgekt/full_outputs/weak_concepts.csv",
        "research/explainability/weak_concept_hit.csv",
        "provider_caches/vikingdb/raw_response.json",
        "vector_indexes/demo/index.hnsw",
        "checkpoints/save2017model.pkl",
        "frontend/dist/index.html",
        "backend/.pytest_cache/v/cache/nodeids",
    }


def test_current_git_tracked_files_do_not_include_banned_large_artifacts() -> None:
    violations = find_banned_tracked_paths(tracked_paths_from_git(ROOT))

    assert violations == []
