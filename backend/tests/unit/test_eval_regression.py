from __future__ import annotations

from datetime import date

from evals.copy_audit_compare.regression import is_due

BUNDLE = {
    "generator": "moments-generator-v28-shared-quotes",
    "auditor": "moments-auditor-v22-enumerated-codes",
    "rule": "preview-v13-headline-hook",
    "model": "glm-5.2",
}


def test_regression_runs_on_first_run_on_any_version_change_and_weekly() -> None:
    today = date(2026, 10, 8)
    same = {**BUNDLE, "date": "2026-10-05"}

    assert is_due(None, BUNDLE, today) == "first run"
    assert is_due(same, BUNDLE, today) is None
    assert is_due(
        {**same, "auditor": "moments-auditor-v21-lean-context"}, BUNDLE, today
    ).startswith("auditor changed")
    assert is_due({**BUNDLE, "date": "2026-10-01"}, BUNDLE, today) == "weekly"
