from __future__ import annotations

import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from backend.app.importing.dataset_safety import (  # noqa: E402
    find_banned_tracked_paths,
    tracked_paths_from_git,
)


def main() -> None:
    violations = find_banned_tracked_paths(tracked_paths_from_git(REPO_ROOT))
    payload = {
        "status": "failed" if violations else "ok",
        "violation_count": len(violations),
        "violations": [
            {"path": violation.path, "pattern": violation.pattern}
            for violation in violations
        ],
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    if violations:
        raise SystemExit(2)


if __name__ == "__main__":
    main()
