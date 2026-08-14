#!/usr/bin/env bash
set -Eeuo pipefail

readonly PIP_TOOLS_VERSION="7.6.1"

python - <<'PY'
from importlib.metadata import version

expected = "7.6.1"
actual = version("pip-tools")
if actual != expected:
    raise SystemExit(
        f"pip-tools {expected} is required to regenerate locks (installed: {actual})"
    )
PY

export CUSTOM_COMPILE_COMMAND="${CUSTOM_COMPILE_COMMAND:-make python-lock}"

python -m piptools compile \
    --generate-hashes \
    --resolver=backtracking \
    --strip-extras \
    --output-file=requirements/runtime.lock \
    pyproject.toml

python -m piptools compile \
    --extra=dev \
    --generate-hashes \
    --resolver=backtracking \
    --strip-extras \
    --output-file=requirements/dev.lock \
    pyproject.toml

printf 'python_locks_generated pip_tools_version=%s\n' "${PIP_TOOLS_VERSION}"
