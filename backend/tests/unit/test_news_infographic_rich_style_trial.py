"""The reviewed rich WorldSkills sample is isolated from formal daily posters."""

# ruff: noqa: RUF001, ASYNC240 -- exact sample and local artifact checks are intentional.

from __future__ import annotations

import json
from contextlib import asynccontextmanager
from copy import deepcopy
from hashlib import sha256
from pathlib import Path
from typing import Any

import app.application.services.news_infographic as posters
import app.application.services.wecom_news_infographic as production
import app.news_infographic_local_main as local_main
import pytest
from app.application.ports.image_generation import ImageReference
from app.application.services.news_infographic import (
    InfographicRunError,
    build_reviewed_rich_worldskills_copy,
    run_local_batch,
    validate_poster_copy,
    validate_reviewed_rich_worldskills_copy,
)
from app.domain.news_infographic import ValidatedInfographicInput, validate_package_snapshot
from app.infrastructure.news_infographic_local import write_frozen_input_bundle
from test_news_infographic import BRAND_ID, EVIDENCE_ID, package_payload
from test_news_infographic_pipeline import _Models, _png


def _worldskills_case(monkeypatch: pytest.MonkeyPatch) -> ValidatedInfographicInput:
    payload: dict[str, Any] = deepcopy(package_payload())
    payload["id"] = str(posters._RICH_WORLD_SKILLS_PACKAGE_ID)
    payload["topic"]["business_date"] = "2026-09-24"
    payload["copy"]["copywriting"] = (
        "小赛洞察：要积极开展人工智能通识教育。\n"
        "新闻来源：中国政府网要闻\n"
        f"原文链接：{posters._RICH_WORLD_SKILLS_SOURCE_URL}"
    )
    facts = (
        "国务院总理李强9月23日上午在上海出席2026年世界技能大会开幕式并致辞。",
        "要积极开展人工智能通识教育，帮助劳动者实现技能转型。",
    )
    brands = (
        "我们不直接把答案塞给孩子，而是引导孩子自己拆解和分析问题。",
        "我们的目标是让孩子学会质疑，而不是被动接受。",
    )
    payload["copy"]["claims"] = [
        {
            "claim_id": f"claim-{index}",
            "kind": "external_fact" if index < 3 else "brand_statement",
            "text": text,
            "evidence_ids": [EVIDENCE_ID] if index < 3 else [],
            "brand_chunk_ids": [] if index < 3 else [BRAND_ID],
        }
        for index, text in enumerate((*facts, *brands), start=1)
    ]
    source = payload["sources"][0]
    source.update(
        {
            "claim_id": "claim-1",
            "claim_text": facts[0],
            "source_url": posters._RICH_WORLD_SKILLS_SOURCE_URL,
            "published_at": "2026-09-23T00:00:00+08:00",
            "exact_quote": " ".join(facts),
        }
    )
    second_source = deepcopy(source)
    second_source.update({"claim_id": "claim-2", "claim_text": facts[1]})
    payload["sources"] = [source, second_source]
    brand = payload["brand_bindings"][0]
    brand.update({"claim_id": "claim-3", "claim_text": brands[0], "text": " ".join(brands)})
    second_brand = deepcopy(brand)
    second_brand.update({"claim_id": "claim-4", "claim_text": brands[1]})
    payload["brand_bindings"] = [brand, second_brand]
    case = validate_package_snapshot(payload)
    monkeypatch.setattr(posters, "_RICH_WORLD_SKILLS_INPUT_FINGERPRINT", case.fingerprint)
    return case


def _references(monkeypatch: pytest.MonkeyPatch) -> tuple[ImageReference, ...]:
    character = _png((10, 10))
    style = _png((11, 11))
    monkeypatch.setattr(posters, "_RICH_WORLD_SKILLS_STYLE_SHA256", sha256(style).hexdigest())
    return (
        ImageReference(
            role="approved-characters",
            asset_id="character",
            filename="character.png",
            sha256=sha256(character).hexdigest(),
            image_bytes=character,
        ),
        ImageReference(
            role="approved-style",
            asset_id="style",
            filename="style.png",
            sha256=sha256(style).hexdigest(),
            image_bytes=style,
        ),
    )


def test_rich_output_root_cannot_follow_a_symlink(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(local_main, "_WORKSPACE_ROOT", tmp_path)
    outside = tmp_path / "outside"
    outside.mkdir()
    (tmp_path / "output").symlink_to(outside, target_is_directory=True)
    with pytest.raises(ValueError, match="real directory"):
        local_main._manual_retry_output_root(tmp_path)


class _AuditModels(_Models):
    def __init__(self, *, accepted: bool = True) -> None:
        super().__init__()
        self.accepted = accepted

    async def complete_json(self, prompt: str) -> dict[str, object]:
        self.prompts.append(prompt)
        return {"accepted": self.accepted, "issues": [] if self.accepted else ["fact"]}


def test_reviewed_rich_copy_is_exact_case_bound_without_relaxing_old_validator(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    case = _worldskills_case(monkeypatch)
    copy = build_reviewed_rich_worldskills_copy(case)
    assert len(copy.cards[0].body) > 75
    assert len(copy.cards[1].body) > 70
    assert len(copy.cards[2].body) > 70
    with pytest.raises(InfographicRunError, match="brand heading"):
        validate_poster_copy(case, copy)
    with pytest.raises(InfographicRunError, match="approved text"):
        validate_reviewed_rich_worldskills_copy(
            case, copy.model_copy(update={"news_summary": "新增未经审核事实。"})
        )
    changed_brand = case.model_copy(
        update={
            "claims": (
                *case.claims[:3],
                case.claims[3].model_copy(update={"text": "保证所有孩子掌握人工智能。"}),
            )
        }
    )
    monkeypatch.setattr(posters, "_RICH_WORLD_SKILLS_INPUT_FINGERPRINT", changed_brand.fingerprint)
    with pytest.raises(InfographicRunError, match="claim differs"):
        validate_reviewed_rich_worldskills_copy(changed_brand, copy)


@pytest.mark.asyncio
async def test_rich_trial_is_one_image_attempt_and_not_send_ready(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    case = _worldskills_case(monkeypatch)
    references = _references(monkeypatch)
    models = _AuditModels()
    summary = await run_local_batch(
        (case,),
        run_dir=tmp_path / "first",
        models=models,
        references=references,
        exact_text_quality_trial=True,
        evidence_first_copy_trial=True,
        model_rendered_text_trial=True,
        rich_worldskills_trial=True,
    )
    assert len(models.prompts) == len(models.image_requests) == 1
    assert summary.cases[0]["generation"] == "generated"
    assert summary.cases[0]["footer"] == "passed"
    assert summary.cases[0]["group_image_sha256"]
    assert "".join(summary.cases[0]["footer_source_url_lines"]) == case.source_url
    assert (
        sha256((summary.run_dir / str(summary.cases[0]["image"])).read_bytes()).hexdigest()
        == summary.cases[0]["image_sha256"]
    )
    assert (
        sha256((summary.run_dir / str(summary.cases[0]["group_image"])).read_bytes()).hexdigest()
        == summary.cases[0]["group_image_sha256"]
    )
    manifest = json.loads((summary.run_dir / "manifest.json").read_text())
    snapshot = json.loads((summary.run_dir / "private/01-image-request.json").read_text())
    assert manifest["send_ready"] is False
    assert manifest["body_text_verification"] == "not_checked"
    assert manifest["trial_version"] == posters._RICH_WORLD_SKILLS_TRIAL_VERSION
    assert snapshot["schema_version"] == posters._RICH_WORLD_SKILLS_PROMPT_VERSION
    assert snapshot["reviewed_copy_document_sha256"] == posters._RICH_WORLD_SKILLS_COPY_MD_SHA256
    assert snapshot["references"][1]["sha256"] == references[1].sha256
    assert snapshot["prompt"] == models.image_requests[0].prompt
    assert (summary.run_dir / "private/01-image.intent.json").is_file()
    assert (tmp_path / f".rich-worldskills-{snapshot['request_fingerprint']}.intent.json").is_file()
    second = _AuditModels()
    retry = await run_local_batch(
        (case,),
        run_dir=tmp_path / "second",
        models=second,
        references=references,
        exact_text_quality_trial=True,
        evidence_first_copy_trial=True,
        model_rendered_text_trial=True,
        rich_worldskills_trial=True,
    )
    assert retry.cases[0]["generation"] == "blocked_preflight"
    assert retry.cases[0]["reason_code"] == "rich_image_already_reserved"
    assert second.image_requests == []
    assert not (retry.run_dir / "private/01-image.intent.json").exists()


@pytest.mark.asyncio
async def test_rich_audit_rejection_never_reserves_image(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    case = _worldskills_case(monkeypatch)
    models = _AuditModels(accepted=False)
    summary = await run_local_batch(
        (case,),
        run_dir=tmp_path / "audit-rejected",
        models=models,
        references=_references(monkeypatch),
        exact_text_quality_trial=True,
        evidence_first_copy_trial=True,
        model_rendered_text_trial=True,
        rich_worldskills_trial=True,
    )
    assert summary.cases[0]["copy"] == "failed"
    assert models.image_requests == []
    assert not list(tmp_path.glob(".rich-worldskills-*.intent.json"))


@pytest.mark.asyncio
async def test_rich_cli_uses_pinned_assets_and_no_send(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    case = _worldskills_case(monkeypatch)
    monkeypatch.setattr(local_main, "_WORKSPACE_ROOT", tmp_path)
    output = tmp_path / "output"
    output.mkdir()
    input_path = output / "input.json"
    write_frozen_input_bundle(input_path, (case,))
    copy = build_reviewed_rich_worldskills_copy(case)
    copy_doc = output / "daily-news-infographic-reference-match-skills-20260925-b.copy.md"
    copy_doc.write_text(
        "\n".join(
            (
                f"主标题：{copy.title}",
                f"导语：{copy.news_summary}",
                f"蓝色卡｜{copy.cards[0].heading}",
                copy.cards[0].body,
                f"绿色卡｜{copy.cards[1].heading}",
                copy.cards[1].body,
                f"紫色卡｜{copy.cards[2].heading}",
                copy.cards[2].body,
                f"页脚：新闻日期：{case.source_date.isoformat()}　新闻来源：{case.source_name}",
                f"原文链接：{case.source_url}",
            )
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        local_main, "_RICH_WORLD_SKILLS_COPY_MD_SHA256", sha256(copy_doc.read_bytes()).hexdigest()
    )
    character = tmp_path / local_main._CHARACTER_REFERENCE.relative_to(local_main._PROJECT_ROOT)
    character.parent.mkdir(parents=True)
    character.write_bytes(_png((10, 10)))
    monkeypatch.setattr(
        production, "_APPROVED_CHARACTER_SHA256", sha256(character.read_bytes()).hexdigest()
    )
    style = output / "daily-news-infographic-rich-preview-20260925-d.png"
    style.write_bytes(_png((11, 11)))
    style_sha = sha256(style.read_bytes()).hexdigest()
    monkeypatch.setattr(local_main, "_RICH_WORLD_SKILLS_STYLE_SHA256", style_sha)
    monkeypatch.setattr(posters, "_RICH_WORLD_SKILLS_STYLE_SHA256", style_sha)
    models = _AuditModels()

    @asynccontextmanager
    async def fake_models(_settings: object) -> Any:
        yield models

    monkeypatch.setattr(local_main, "get_settings", lambda: object())
    monkeypatch.setattr(local_main, "local_infographic_models", fake_models)
    args = local_main._parser().parse_args(
        [
            "run",
            "--input-bundle",
            str(input_path),
            "--output-dir",
            str(output / "rich-first"),
            "--approved-asset-root",
            str(tmp_path),
            "--rich-worldskills-trial",
            "--execute",
        ]
    )
    assert await local_main._run(args) == 0
    assert len(models.image_requests) == 1
    manifest = json.loads((output / "rich-first/manifest.json").read_text())
    assert manifest["send_ready"] is False
    assert manifest["cases"][0]["group_image_sha256"]
    style.write_bytes(_png((12, 12)))
    with pytest.raises(ValueError, match="reference assets have changed"):
        await local_main._run(
            local_main._parser().parse_args(
                [
                    "run",
                    "--input-bundle",
                    str(input_path),
                    "--output-dir",
                    str(output / "rich-tampered"),
                    "--approved-asset-root",
                    str(tmp_path),
                    "--rich-worldskills-trial",
                    "--execute",
                ]
            )
        )
    assert not (output / "rich-tampered").exists()
    assert len(models.image_requests) == 1
