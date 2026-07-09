from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .assist2017_artifacts import (
    Assist2017BuildError,
    build_assist2017_import_artifacts,
)


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Build V1.5 ASSISTments2017 mapping, content, RAG, coverage, "
            "and smoke artifacts from local source rows."
        )
    )
    parser.add_argument(
        "--source-rows",
        required=True,
        help="Path to ASSISTments2017-style source rows CSV.",
    )
    parser.add_argument(
        "--q-matrix",
        required=True,
        help="Path to ASSISTments2017 Q-matrix CSV.",
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

    try:
        artifacts = build_assist2017_import_artifacts(
            source_rows_path=args.source_rows,
            q_matrix_path=args.q_matrix,
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
