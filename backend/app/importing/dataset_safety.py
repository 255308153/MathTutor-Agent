from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass
from pathlib import Path


BANNED_TRACKED_PATH_PATTERNS = [
    r"(^|/)(node_modules|dist|build|__pycache__|\.pytest_cache|\.ruff_cache|\.mypy_cache|\.next|\.cache|cache)(/|$)",
    r"(^|/)(checkpoints?|model/runs)(/|$)",
    r"\.(pkl|pt|pth|ckpt|safetensors)$",
    r"^data/(local|raw|full)(/|$)",
    r"^data/import/(assist2017|full)(/|$)",
    r"^data/.*/[^/]*(train|test)[^/]*\.(csv|json|jsonl|txt|tsv)$",
    r"^data/imported/(?!assist2017_fixture/)",
    r"^outputs/",
    r"^logs/",
]

COMMITTABLE_FIXTURE_PATH_PATTERNS = [
    r"^data/content/demo_teaching_content\.json$",
    r"^data/rag/demo_knowledge\.json$",
    r"^data/import/[^/]+\.fixture\.csv$",
    r"^data/mapping/[^/]+\.fixture\.(csv|json)$",
    r"^data/imported/assist2017_fixture/(canonical_mapping|content_import|coverage_report|rag_documents|smoke_dataset)\.json$",
]


@dataclass(frozen=True)
class TrackedPathViolation:
    path: str
    pattern: str


def tracked_paths_from_git(repo_root: str | Path = ".") -> list[str]:
    result = subprocess.run(
        ["git", "ls-files", "-z"],
        cwd=repo_root,
        check=True,
        capture_output=True,
    )
    return [
        path
        for path in result.stdout.decode("utf-8").split("\0")
        if path
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
