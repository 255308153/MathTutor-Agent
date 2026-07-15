from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass
from pathlib import Path


BANNED_TRACKED_PATH_PATTERNS = [
    r"(^|/)\.env(\..*)?$",
    r"(^|/)(secrets?|credentials?)(/|$)",
    r"(^|/)[^/]*(secret|credential|api[_-]?key|token)[^/]*\.(env|json|ya?ml|toml|txt)$",
    r"(^|/)(node_modules|dist|build|__pycache__|\.pytest_cache|\.ruff_cache|\.mypy_cache|\.next|\.cache|cache)(/|$)",
    r"(^|/)(provider[-_]?caches?|mem0[-_]?cache|vikingdb[-_]?cache|openviking[-_]?cache)(/|$)",
    r"(^|/)(generated[-_]?vector[-_]?indexes?|vector[-_]?indexes?)(/|$)",
    r"(^|/)(chroma|faiss|annoy)[-_]?(index|indexes|store|cache|db)(/|$)",
    r"(^|/)(checkpoints?|model/runs)(/|$)",
    r"\.(faiss|hnsw|ann|index)$",
    r"\.(pkl|pt|pth|ckpt|safetensors)$",
    r"^data/(local|raw|full)(/|$)",
    r"^data/(provider[-_]?caches?|generated[-_]?vector[-_]?indexes?|vector[-_]?indexes?)(/|$)",
    r"^data/import/(xes3g5m|full)(/|$)",
    r"^data/.*/[^/]*(train|test)[^/]*\.(csv|json|jsonl|txt|tsv)$",
    r"^data/imported/(?!xes3g5m_fixture/)",
    r"(^|/)(attribution_paths|key_history|path_ablation|weak_concepts|weak_concept_hit|stability|explanation_baselines|diagnosis_cases)\.(csv|json|md)$",
    r"^outputs/",
    r"^logs/",
]

COMMITTABLE_FIXTURE_PATH_PATTERNS = [
    r"^\.env\.example$",
    r"^data/content/demo_teaching_content\.json$",
    r"^data/rag/demo_knowledge\.json$",
    r"^data/import/[^/]+\.fixture\.csv$",
    r"^data/mapping/[^/]+\.fixture\.(csv|json)$",
    r"^data/imported/xes3g5m_fixture/(canonical_mapping|content_import|coverage_report|rag_documents|smoke_dataset)\.json$",
    r"^data/dgekt/offline_evidence_fixture/(attribution_paths|key_history|path_ablation|weak_concepts)\.csv$",
    r"^data/dgekt/offline_evidence_fixture/diagnosis_cases\.json$",
]


@dataclass(frozen=True)
class TrackedPathViolation:
    path: str
    pattern: str


def tracked_paths_from_git(repo_root: str | Path = ".") -> list[str]:
    root = Path(repo_root)
    result = subprocess.run(
        ["git", "ls-files", "-z"],
        cwd=root,
        check=True,
        capture_output=True,
    )
    return [
        path
        for path in result.stdout.decode("utf-8").split("\0")
        if path and (root / path).exists()
    ]


def find_banned_tracked_paths(paths: list[str]) -> list[TrackedPathViolation]:
    violations: list[TrackedPathViolation] = []
    for path in paths:
        if _matches_any(path, COMMITTABLE_FIXTURE_PATH_PATTERNS):
            continue
        for pattern in BANNED_TRACKED_PATH_PATTERNS:
            if re.search(pattern, path, flags=re.IGNORECASE):
                violations.append(TrackedPathViolation(path=path, pattern=pattern))
                break
    return violations


def _matches_any(path: str, patterns: list[str]) -> bool:
    return any(re.search(pattern, path, flags=re.IGNORECASE) for pattern in patterns)
