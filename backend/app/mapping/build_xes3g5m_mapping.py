from __future__ import annotations

import argparse
import json
from pathlib import Path

from .xes3g5m_mapping import build_mapping_artifact, coverage_diagnostics


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Build a small canonical XES3G5M question/concept mapping artifact."
    )
    parser.add_argument("--kc-routes", required=True, help="Path to XES3G5M KC routes CSV.")
    parser.add_argument("--metadata", required=True, help="Path to curated mapping metadata JSON.")
    parser.add_argument("--teaching-content", help="Optional local teaching content JSON.")
    parser.add_argument("--rag-docs", help="Optional local RAG documents JSON.")
    parser.add_argument("--output", required=True, help="Output canonical mapping artifact JSON.")
    args = parser.parse_args()

    artifact = build_mapping_artifact(
        kc_routes_path=args.kc_routes,
        metadata_path=args.metadata,
        teaching_content_path=args.teaching_content,
        rag_docs_path=args.rag_docs,
        output_path=args.output,
    )

    teaching_content = (
        json.loads(Path(args.teaching_content).read_text(encoding="utf-8"))
        if args.teaching_content
        else None
    )
    rag_docs = (
        json.loads(Path(args.rag_docs).read_text(encoding="utf-8")) if args.rag_docs else None
    )
    report = coverage_diagnostics(
        artifact,
        kc_routes_path=args.kc_routes,
        teaching_content=teaching_content,
        rag_docs=rag_docs,
    ).to_report()
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
