# ruff: noqa: RUF001
"""Asset-label eval: strict parsing, one retry on invalid output, scoring, metadata draft."""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

import pytest
from evals.asset_labels.client import ChatResult, label_image
from evals.asset_labels.labels import (
    AssetLabels,
    InvalidLabels,
    Truth,
    metadata_draft,
    parse_labels,
    score,
)
from evals.asset_labels.runner import ModelRun, card_of, render, run_model
from PIL import Image

VALID = {
    "asset_kind": "action",
    "characters": ["sai-xiansheng"],
    "props": ["microscope"],
    "poses": ["observe"],
    "scene_tags": ["experiment"],
    "note": "显微镜前观察",
}


def test_parse_accepts_fenced_json_and_normalizes_identity_sheets() -> None:
    fenced = "```json\n" + json.dumps(VALID, ensure_ascii=False) + "\n```"
    identity = {**VALID, "asset_kind": "identity", "poses": ["point"], "scene_tags": ["classroom"]}

    action = parse_labels(fenced)
    sheet = parse_labels(json.dumps(identity))

    assert action.props == ["microscope"]
    assert (sheet.props, sheet.poses, sheet.scene_tags) == ([], [], ["brand"])


@pytest.mark.parametrize(
    "text",
    [
        "没有 JSON",
        '{"asset_kind": "action", "characters": [],}',
        json.dumps({**VALID, "props": ["lab_coat"]}),
        json.dumps({**VALID, "characters": ["dr-owl"]}),
        json.dumps({**VALID, "extra": 1}),
        json.dumps({**VALID, "props": ["book", "telescope", "microscope"]}),
    ],
)
def test_parse_rejects_anything_outside_the_vocabularies(text: str) -> None:
    with pytest.raises(InvalidLabels):
        parse_labels(text)


class _Fake:
    name = "fake-vl"

    def __init__(self, replies: Sequence[str]) -> None:
        self.replies = list(replies)
        self.requests: list[Sequence[Mapping[str, Any]]] = []

    def complete(self, content: Sequence[Mapping[str, Any]]) -> ChatResult:
        self.requests.append(content)
        return ChatResult(self.replies.pop(0), 1000, 50, 0.5)


def _png(path: Path) -> Path:
    Image.new("RGBA", (64, 48), (0, 120, 200, 255)).save(path)
    return path


def test_label_image_retries_once_with_the_error_then_gives_up(tmp_path: Path) -> None:
    image, ref = _png(tmp_path / "a.png"), _png(tmp_path / "r.png")
    fixed = _Fake(["not json", json.dumps(VALID)])
    broken = _Fake(["not json", "still not json", json.dumps(VALID)])

    ok = label_image(fixed, image, references=[ref])
    bad = label_image(broken, image, references=[ref])

    assert ok.labels is not None and ok.calls == 2 and ok.prompt_tokens == 2000
    retry_text = fixed.requests[1][-1]["text"]
    assert "不合法" in retry_text and "no JSON object" in retry_text
    # one reference, the image and the guide; images are data URLs
    assert [part["type"] for part in fixed.requests[0]] == ["image_url", "image_url", "text"]
    assert fixed.requests[0][0]["image_url"]["url"].startswith("data:image/jpeg;base64,")
    assert bad.labels is None and bad.calls == 2 and bad.error


def _truth(**values: Any) -> Truth:
    base = {
        "asset_kind": "action",
        "characters": frozenset({"sai-xiansheng"}),
        "props": frozenset({"microscope"}),
        "poses": frozenset({"observe"}),
        "scene_tags": frozenset({"experiment"}),
    }
    return Truth(**{**base, **values})


def test_scoring_counts_exact_sets_and_per_value_errors() -> None:
    right = AssetLabels.model_validate(VALID)
    wrong_prop = AssetLabels.model_validate({**VALID, "props": ["specimen"]})
    sheet = AssetLabels.model_validate(
        {**VALID, "asset_kind": "identity", "characters": ["xiao-sai"]}
    ).normalized()

    card = score(
        [
            (right, _truth()),
            (wrong_prop, _truth()),
            (sheet, _truth(asset_kind="identity", characters=frozenset({"xiao-sai"}))),
            (None, _truth()),
        ]
    )

    assert (card.kind_correct, card.kind_total, card.invalid) == (3, 3, 1)
    assert (card.characters.exact, card.characters.total) == (3, 3)
    # props, poses and scenes only on action images
    assert (card.props.exact, card.props.total) == (1, 2)
    assert card.props.per_value(["microscope", "specimen"]) == {
        "microscope": (1, 0, 1),
        "specimen": (0, 1, 0),
    }
    assert card.props.micro() == (0.5, 0.5)


def test_run_model_stops_at_the_call_cap_and_keeps_labelled_rows(tmp_path: Path) -> None:
    references = ("ref-xiao-sai.png", "a0.png")
    _png(tmp_path / references[0])
    assets: list[dict[str, Any]] = [
        {"relative_path": f"a{i}.png", "asset_kind": "action", "characters": ["sai-xiansheng"]}
        for i in range(3)
    ]
    for asset in assets:
        _png(tmp_path / asset["relative_path"])
    budget = {"left": 3}

    def spend(calls: int) -> None:
        budget["left"] -= calls

    run = run_model(
        _Fake([json.dumps(VALID)] * 3),
        assets,
        tmp_path,
        references=references,
        calls_left=lambda: budget["left"],
        spend=spend,
    )

    assert (len(run.rows), run.calls, run.capped) == (2, 2, True)
    assert [row["is_reference"] for row in run.rows] == [True, False]
    assert run.rows[0]["truth"]["props"] == [] and run.rows[0]["labels"]["props"] == ["microscope"]


def test_render_reports_aggregates_without_paths() -> None:
    row = {
        "relative_path": "05-visual-assets/secret-name.png",
        "is_reference": False,
        "truth": {
            "asset_kind": "action",
            "characters": ["sai-xiansheng"],
            "props": ["microscope"],
            "poses": ["observe"],
            "scene_tags": ["experiment"],
        },
        "labels": {**VALID, "props": ["specimen"]},
        "calls": 1,
        "error": None,
    }
    run = ModelRun(model="fake-vl", rows=[row], calls=1, prompt_tokens=1000, completion_tokens=50)

    text = render([run], assets=1, actions=1)

    assert card_of(run).props.exact == 0
    assert "microscope → specimen ×1" in text
    assert "secret-name" not in text


def test_metadata_draft_is_unapproved_and_keeps_props_for_action_images() -> None:
    action = metadata_draft(AssetLabels.model_validate(VALID), model="qwen3-vl-plus")
    sheet = metadata_draft(
        AssetLabels.model_validate({**VALID, "asset_kind": "identity"}).normalized(),
        model="qwen3-vl-plus",
    )

    assert action["approved"] is False and action["props"] == ["microscope"]
    assert "props" not in sheet and sheet["scene_tags"] == ["brand"]
    assert "qwen3-vl-plus" in action["manual_review_note"]
