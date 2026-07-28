"""Export or verify the deterministic FastAPI OpenAPI document."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from app.api_main import app

PROJECT_ROOT = Path(__file__).resolve().parents[2]
OPENAPI_PATH = PROJECT_ROOT / "backend" / "openapi.json"


def render_openapi() -> str:
    return json.dumps(app.openapi(), ensure_ascii=False, indent=2, sort_keys=True) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check",
        action="store_true",
        help="Fail when backend/openapi.json is missing or differs from the FastAPI schema.",
    )
    args = parser.parse_args()
    rendered = render_openapi()

    if args.check:
        if not OPENAPI_PATH.exists() or OPENAPI_PATH.read_text(encoding="utf-8") != rendered:
            print("backend/openapi.json is stale; run 'make api-generate'.")
            return 1
        return 0

    OPENAPI_PATH.write_text(rendered, encoding="utf-8")
    print(f"Wrote {OPENAPI_PATH.relative_to(PROJECT_ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
