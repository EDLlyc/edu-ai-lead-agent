
from __future__ import annotations

import pytest
from evals.copy_audit_compare.runner import ConfigTally, parse_configs, render
from evals.copy_quality.runner import CallBudget


def test_configs_parse_and_must_have_unique_names() -> None:
    configs = parse_configs(
        ["prod:moments-auditor-v21-lean-context:glm-5.2", "cheap:v22:glm-4.5-air"]
    )

    assert [(c.name, c.prompt_version, c.model) for c in configs] == [
        ("prod", "moments-auditor-v21-lean-context", "glm-5.2"),
        ("cheap", "v22", "glm-4.5-air"),
    ]
    with pytest.raises(ValueError):
        parse_configs(["a:v1:m", "a:v2:m"])


def test_report_is_paired_per_defect() -> None:
    configs = parse_configs(["prod:v21:glm-5.2", "cheap:v22:glm-4.5-air"])
    prod, cheap = ConfigTally(), ConfigTally()
    prod.defects, prod.blocked, prod.latencies = 2, 1, [1000, 3000]
    prod.by_defect["hook_off_topic"] = [1, 2]
    cheap.defects, cheap.blocked, cheap.latencies = 2, 2, [300, 500]
    cheap.by_defect["hook_off_topic"] = [2, 2]

    text = render(configs, {"prod": prod, "cheap": cheap}, topics=1, budget=CallBudget(limit=5))

    assert "| hook_off_topic | 1/2 | 2/2 |" in text
    assert "| prod | v21 | glm-5.2 | 1/2 |" in text
    assert "| cheap | v22 | glm-4.5-air | 2/2 |" in text
