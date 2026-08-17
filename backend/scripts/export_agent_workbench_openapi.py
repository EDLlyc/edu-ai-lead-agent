"""Export or verify the deterministic local Agent Workbench OpenAPI document."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from app.agent_workbench_api_main import create_agent_workbench_app
from app.core.agent_workbench_config import AgentWorkbenchSettings

PROJECT_ROOT = Path(__file__).resolve().parents[2]
OPENAPI_PATH = PROJECT_ROOT / "backend" / "openapi.agent-workbench.json"
OPENAPI_APP = create_agent_workbench_app(
    settings=AgentWorkbenchSettings(  # type: ignore[call-arg]
        _env_file=None,
        app_env="test",
        agent_workbench_enabled=False,
        agent_workbench_data_mode="fixture",
        agent_workbench_model_mode="deterministic",
        agent_workbench_live_enabled=False,
    )
)


def render_openapi() -> str:
    return json.dumps(OPENAPI_APP.openapi(), ensure_ascii=False, indent=2, sort_keys=True) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check",
        action="store_true",
        help="Fail when the local workbench OpenAPI document is missing or stale.",
    )
    args = parser.parse_args()
    rendered = render_openapi()

    if args.check:
        if not OPENAPI_PATH.exists() or OPENAPI_PATH.read_text(encoding="utf-8") != rendered:
            print("backend/openapi.agent-workbench.json is stale; run 'make agent-api-generate'.")
            return 1
        return 0

    OPENAPI_PATH.write_text(rendered, encoding="utf-8")
    print(f"Wrote {OPENAPI_PATH.relative_to(PROJECT_ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
