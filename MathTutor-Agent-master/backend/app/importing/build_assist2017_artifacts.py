from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .assist2017_artifacts import (
    Assist2017BuildError,
    build_assist2017_import_artifacts,
)

PROJECT_ROOT = Path(__file__).resolve().parents[3]
FIXTURE_SOURCE_ROWS = PROJECT_ROOT / "data" / "import" / "assist2017_source.fixture.csv"
FIXTURE_Q_MATRIX = PROJECT_ROOT / "data" / "mapping" / "assist2017_q_matrix.fixture.csv"


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Build V1.5 ASSISTments2017 mapping, content, RAG, coverage, "
            "and smoke artifacts from local source rows."
        )
    )
    parser.add_argument(
        "--dataset-mode",
        choices=["fixture", "full"],
        default="fixture",
        help=(
            "fixture uses the committed small ASSISTments2017 sample; full requires "
            "explicit local source paths and should write to an ignored local directory."
        ),
    )
    parser.add_argument(
        "--source-rows",
        help=(
            "Path to ASSISTments2017-style source rows CSV. Optional in fixture mode; "
            "required in full mode."
        ),
    )
    parser.add_argument(
        "--q-matrix",
        help=(
            "Path to ASSISTments2017 Q-matrix CSV. Optional in fixture mode; "
            "required in full mode."
        ),
    )
    parser.add_argument(
        "--output-dir",
        required=True,
        help="Directory where V1.5 artifact JSON files will be written.",
    )
    parser.add_argument(
        "--generated-at",
        help="Optional build timestamp. Use a fixed value for deterministic fixture builds.",
    )
    parser.add_argument(
        "--allow-validation-errors",
        action="store_true",
        help="Write artifacts even when validation errors are present; intended for diagnostics.",
    )
    args = parser.parse_args()
    source_rows = Path(args.source_rows) if args.source_rows else FIXTURE_SOURCE_ROWS
    q_matrix = Path(args.q_matrix) if args.q_matrix else FIXTURE_Q_MATRIX
    if args.dataset_mode == "full" and (not args.source_rows or not args.q_matrix):
        parser.error(
            "--dataset-mode full 必须显式设置 --source-rows 和 --q-matrix；"
            "不要让 full-data 构建静默使用 fixture。"
        )

    try:
        artifacts = build_assist2017_import_artifacts(
            source_rows_path=source_rows,
            q_matrix_path=q_matrix,
            output_dir=args.output_dir,
            generated_at=args.generated_at,
            fail_on_errors=not args.allow_validation_errors,
        )
    except Assist2017BuildError as exc:
        payload = {
            "status": "failed",
            "coverage_summary": exc.coverage_summary,
            "validation_errors": [issue.model_dump() for issue in exc.issues],
        }
        print(json.dumps(payload, ensure_ascii=False, indent=2), file=sys.stderr)
        raise SystemExit(2) from exc

    output_dir = Path(args.output_dir)
    payload = {
        "status": "ok",
        "dataset_mode": args.dataset_mode,
        "source_rows": str(source_rows),
        "q_matrix": str(q_matrix),
        "output_dir": str(output_dir),
        "artifacts": {
            "canonical_mapping": str(output_dir / "canonical_mapping.json"),
            "content_import": str(output_dir / "content_import.json"),
            "rag_documents": str(output_dir / "rag_documents.json"),
            "coverage_report": str(output_dir / "coverage_report.json"),
            "smoke_dataset": str(output_dir / "smoke_dataset.json"),
        },
        "coverage_summary": artifacts.coverage.summary,
        "validation_errors": [
            issue.model_dump()
            for issue in artifacts.coverage.metadata.validation_errors
            if issue.severity == "error"
        ],
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
