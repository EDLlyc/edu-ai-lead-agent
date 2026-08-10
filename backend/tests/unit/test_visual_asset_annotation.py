from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import httpx

# The catalog command is intentionally a repository script, not an installed application module.
sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from scripts.annotate_brand_visual_assets import (
    _extract_object,
    _merge_annotation,
    annotate_one,
)


def _asset(*, relative_path: str = "asset.png", asset_kind: str = "action") -> dict[str, Any]:
    return {
        "relative_path": relative_path,
        "filename": Path(relative_path).name,
        "asset_kind": asset_kind,
        "characters": ["xiao-sai"],
        "topics": ["science"],
        "poses": ["observe"],
        "scene_tags": ["experiment"],
    }


def test_extract_object_discards_reasoning_and_accepts_answer_wrapper() -> None:
    content = (
        "<think>provider reasoning that must not be persisted</think>"
        '<answer>{"topics":["robotics"],"poses":"observe"}</answer>'
    )

    assert _extract_object(content) == {"topics": ["robotics"], "poses": "observe"}
    assert "provider reasoning" not in json.dumps(_extract_object(content))


def test_model_labels_are_allowlisted_and_identity_characters_remain_authoritative() -> None:
    result, suggestions = _merge_annotation(
        _asset(asset_kind="identity"),
        {
            "characters": ["sai-xiansheng", "untrusted"],
            "topics": ["robotics", "free-form prompt"],
            "poses": "observe",
            "scene_tags": ["robotics_lab"],
        },
    )

    assert result == {
        "characters": ["xiao-sai"],
        "topics": ["science"],
        "poses": ["observe"],
        "scene_tags": ["experiment"],
    }
    assert suggestions == {
        "characters": ["sai-xiansheng"],
        "topics": ["robotics"],
        "poses": ["observe"],
        "scene_tags": ["robotics_lab"],
    }


def test_provider_rejection_uses_rule_metadata_without_raw_response(tmp_path: Path) -> None:
    asset_path = tmp_path / "asset.png"
    asset_path.write_bytes(b"private image fixture")

    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(400, json={"error": {"message": "provider body must not persist"}})

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        metadata, status = annotate_one(
            client,
            base_url="https://vision.example.test/v4",
            api_key="test-secret",
            model="glm-4.1v-thinking-flash",
            asset=_asset(),
            materials_root=tmp_path,
        )

    assert metadata == {
        "characters": ["xiao-sai"],
        "topics": ["science"],
        "poses": ["observe"],
        "scene_tags": ["experiment"],
    }
    assert status["status"] == "fallback_filename_rule"
    assert status["error_code"] == "provider_rejected"
    assert isinstance(status["request_fingerprint"], str)
    assert len(status["request_fingerprint"]) == 64
    assert set(status) == {"status", "error_code", "request_fingerprint"}
    assert "provider body" not in repr(status)
