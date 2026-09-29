"""Local infographic runs are bounded, replay-safe and honest about every check."""

# ruff: noqa: RUF001 -- exact Chinese poster test copy is intentional.

from __future__ import annotations

import json
import re
import stat
from copy import deepcopy
from hashlib import sha256
from io import BytesIO
from pathlib import Path
from uuid import uuid4

import app.news_infographic_local_main as local_main
import pytest
from app.application.ports.image_generation import (
    ImageGenerationRequest,
    ImageGenerationResult,
    ImageReference,
    validate_image_generation_request_prompt,
)
from app.application.ports.image_validation import (
    ImageQualityAuditRequest,
    ImageQualityAuditResult,
    ImageTextRecognitionRequest,
    ImageTextRecognitionResult,
)
from app.application.services.news_infographic import (
    COPY_VERSION,
    GEOMETRY,
    PROMPT_VERSION,
    InfographicRunError,
    ManualImageRetry,
    PosterCard,
    PosterCopy,
    ReviewedPosterCards,
    _private_copy_schema_diagnostic,
    build_copy_audit_prompt,
    build_copy_prompt,
    build_evidence_first_copy,
    build_image_prompt,
    build_model_rendered_image_prompt,
    build_reviewed_card_copy,
    render_preview,
    run_local_batch,
    validate_poster_copy,
)
from app.core.errors import (
    ImageOutputValidationError,
    ImageProviderConfigurationError,
    ImageProviderQuotaError,
    ImageProviderRejectedError,
    ImageProviderTimeoutError,
    InvalidProviderOutputError,
    ProviderAuthenticationError,
    ProviderIdentityMismatchError,
    ProviderInputLimitError,
    ProviderRateLimitError,
    ProviderRejectedError,
    ProviderTimeoutError,
    ProviderUnavailableError,
)
from app.domain.news_infographic import ValidatedInfographicInput, validate_package_snapshot
from PIL import Image
from test_news_infographic import package_payload


def _copy_payload() -> dict[str, object]:
    return {
        "title": "教育部介绍科学课探究",
        "news_summary": "教育部介绍科学课探究相关内容。",
        "news_claim_ids": ["fact-1"],
        "cards": [
            {
                "kind": "science",
                "heading": "科学课探究",
                "body": "教育部介绍了科学课探究。",
                "claim_ids": ["fact-1"],
            },
            {
                "kind": "learning",
                "heading": "可以这样提问",
                "body": "孩子可以问：科学课怎样探究？",
                "claim_ids": ["fact-1"],
            },
            {
                "kind": "brand",
                "heading": "赛先生鼓励孩子提问",
                "body": "赛先生鼓励孩子提问。",
                "claim_ids": ["brand-1"],
            },
        ],
    }


def _evidence_first_cases() -> tuple[ValidatedInfographicInput, ...]:
    fact_texts = (
        "科学课鼓励学生观察身边现象，并记录自己提出的问题。",
        "新闻介绍校园开展科学活动，学生在活动中记录观察结果。",
        "教育部门发布科学教育活动安排，学校将组织学生参与探究活动。",
    )
    brand_texts = (
        "赛先生鼓励孩子提问，也鼓励孩子观察身边现象。",
        "赛先生重视孩子的好奇心，支持孩子自主提出问题。",
        "赛先生支持孩子主动探索，并记录自己的发现。",
    )
    cases = []
    for fact_text, brand_text in zip(fact_texts, brand_texts, strict=True):
        payload = deepcopy(package_payload())
        payload["id"] = str(uuid4())
        payload["copy_generation_run_id"] = str(uuid4())
        payload["topic"]["selected_event_id"] = str(uuid4())
        payload["topic"]["selected_event_version_id"] = str(uuid4())
        payload["copy"]["draft_version_id"] = str(uuid4())
        payload["copy"]["claims"][0]["text"] = fact_text
        payload["copy"]["claims"][1]["text"] = brand_text
        payload["sources"][0]["claim_text"] = fact_text
        payload["sources"][0]["exact_quote"] = fact_text
        payload["brand_bindings"][0]["claim_text"] = brand_text
        cases.append(validate_package_snapshot(payload))
    return tuple(cases)


def _png(size: tuple[int, int] = GEOMETRY) -> bytes:
    buffer = BytesIO()
    Image.new("RGB", size, (211, 230, 245)).save(buffer, format="PNG")
    return buffer.getvalue()


class _Models:
    copy_model = "fake-copy-v1"
    image_model = "fake-portrait-v1"
    ocr_enabled = True
    visual_audit_enabled = True

    def __init__(
        self, *, fail_image: str | None = None, recognize: bool = True, bad_ocr: bool = False
    ) -> None:
        self.prompts: list[str] = []
        self.image_requests: list[ImageGenerationRequest] = []
        self.ocr_requests: list[ImageTextRecognitionRequest] = []
        self.visual_requests: list[ImageQualityAuditRequest] = []
        self.fail_image = fail_image
        self.do_recognize = recognize
        self.bad_ocr = bad_ocr

    async def complete_json(self, prompt: str) -> dict[str, object]:
        self.prompts.append(prompt)
        return {"accepted": True, "issues": []} if "逐句检查" in prompt else _copy_payload()

    async def generate(self, request: ImageGenerationRequest) -> ImageGenerationResult:
        self.image_requests.append(request)
        if self.fail_image == "timeout":
            raise ImageProviderTimeoutError()
        if self.fail_image == "503":
            raise ImageProviderRejectedError(http_status=503)
        if self.fail_image == "unavailable":
            raise ProviderUnavailableError()
        if self.fail_image == "coded_invalid":
            raise ImageOutputValidationError("image_dimensions_invalid")
        size = (1024, 1024) if self.fail_image == "square" else GEOMETRY
        return ImageGenerationResult(
            provider="comfly",
            model=self.image_model,
            request_fingerprint=request.request_fingerprint,
            provider_task_id=None,
            provider_upload_id=None,
            image_bytes=b"not-a-real-png" if self.fail_image == "corrupt" else _png(size),
            media_type="image/png",
            width=size[0],
            height=size[1],
            attempts=1,
        )

    async def recognize(
        self, request: ImageTextRecognitionRequest
    ) -> ImageTextRecognitionResult | None:
        self.ocr_requests.append(request)
        return (
            ImageTextRecognitionResult(
                recognized_lines=("错字",) if self.bad_ocr else request.expected_text,
                request_fingerprint=request.request_fingerprint,
            )
            if self.do_recognize
            else None
        )

    async def audit_visual(
        self, request: ImageQualityAuditRequest
    ) -> ImageQualityAuditResult | None:
        self.visual_requests.append(request)
        return ImageQualityAuditResult(
            accepted=True,
            request_fingerprint=request.request_fingerprint,
        )


def _reference() -> tuple[ImageReference, ...]:
    data = _png((10, 10))
    from hashlib import sha256

    return (
        ImageReference(
            role="approved-characters",
            asset_id="approved-characters",
            filename="reference.png",
            sha256=sha256(data).hexdigest(),
            image_bytes=data,
        ),
    )


def _style_reference() -> tuple[ImageReference, ...]:
    style_bytes = _png((11, 11))
    return (
        *_reference(),
        ImageReference(
            role="approved-style",
            asset_id="approved-style",
            filename="style.png",
            sha256=sha256(style_bytes).hexdigest(),
            image_bytes=style_bytes,
        ),
    )


@pytest.mark.asyncio
async def test_local_run_exports_original_portrait_and_keeps_approval_pending(
    tmp_path: Path,
) -> None:
    case = validate_package_snapshot(package_payload())
    models = _Models()
    run_dir = tmp_path / "fresh"
    summary = await run_local_batch(
        (case,), run_dir=run_dir, models=models, references=_reference()
    )
    assert len(models.prompts) == 2
    assert len(models.image_requests) == 1
    assert models.image_requests[0].reference_mode == "multi"
    assert summary.cases[0]["generation"] == "generated"
    assert summary.cases[0]["decode"] == "passed"
    assert summary.cases[0]["footer"] == "passed"
    assert "".join(summary.cases[0]["footer_source_url_lines"]) == case.source_url
    assert summary.cases[0]["ocr"] == "passed"
    assert summary.cases[0]["human_inspection"] == "pending"
    assert summary.batch_accepted is False
    image_file = run_dir / str(summary.cases[0]["image"])
    assert image_file.read_bytes() == _png()
    derived_file = run_dir / str(summary.cases[0]["derived_image"])
    assert derived_file.read_bytes() != image_file.read_bytes()
    assert sha256(image_file.read_bytes()).hexdigest() == summary.cases[0]["image_sha256"]
    assert sha256(derived_file.read_bytes()).hexdigest() == summary.cases[0]["derived_image_sha256"]
    request_file = run_dir / "private" / "01-image-request.json"
    request_snapshot = json.loads(request_file.read_text(encoding="utf-8"))
    assert stat.S_IMODE(request_file.stat().st_mode) == 0o600
    assert request_snapshot["copy"]["title"] == _copy_payload()["title"]
    assert request_snapshot["geometry"] == {"width": 1152, "height": 2048}
    assert request_snapshot["schema_version"] == PROMPT_VERSION
    assert request_snapshot["prompt"] == models.image_requests[0].prompt
    assert request_snapshot["prompt"] == " ".join(request_snapshot["prompt"].split())
    assert request_snapshot["request_fingerprint"] == models.image_requests[0].request_fingerprint
    assert request_snapshot["references"][0]["sha256"] == _reference()[0].sha256
    assert not (run_dir / "private" / "01-copy-candidate.json").exists()
    assert not (run_dir / "private" / "01-copy-audit-verdict.json").exists()
    preview = (run_dir / "preview.html").read_text(encoding="utf-8")
    assert case.source_url in preview
    assert str(summary.cases[0]["derived_image"]) in preview
    assert "private_path" not in preview
    assert "通过提问引导孩子拆解问题" not in preview
    assert "2026-08-04" in preview
    with pytest.raises(FileExistsError):
        await run_local_batch((case,), run_dir=run_dir, models=models, references=_reference())
    assert len(models.image_requests) == 1


@pytest.mark.asyncio
async def test_exact_text_quality_trial_uses_formal_prompt_and_final_group_jpeg(
    tmp_path: Path,
) -> None:
    case = validate_package_snapshot(package_payload())
    models = _Models()
    run_dir = tmp_path / "exact-trial"
    summary = await run_local_batch(
        (case,),
        run_dir=run_dir,
        models=models,
        references=_reference(),
        exact_text_quality_trial=True,
    )
    outcome = summary.cases[0]
    assert len(models.image_requests) == 1
    assert len(models.prompts) == 2
    assert "顶部x35-874" in models.image_requests[0].prompt
    assert "由程序写字" in models.image_requests[0].prompt
    assert outcome["generation"] == "generated"
    assert outcome["overlay"] == "passed"
    assert outcome["footer"] == "passed"
    assert outcome["footer_version"] == "daily-news-infographic-footer-v6-none"
    assert outcome["poster_region_ocr"] == "not_checked"
    assert outcome["ocr"] == "not_checked_region_gate"
    assert not models.ocr_requests
    assert outcome["footer_source_url_lines"] == []  # 图片上不放链接
    raw = (run_dir / str(outcome["image"])).read_bytes()
    composite = (run_dir / str(outcome["composite_image"])).read_bytes()
    footer = (run_dir / str(outcome["derived_image"])).read_bytes()
    group = (run_dir / str(outcome["group_image"])).read_bytes()
    phone = (run_dir / str(outcome["phone_preview"])).read_bytes()
    # Footer v6 draws nothing, so the footer step leaves the composite unchanged.
    assert len({sha256(item).hexdigest() for item in (raw, composite, group)}) == 3
    assert footer == composite
    assert len(group) <= 2 * 1024 * 1024
    assert sha256(group).hexdigest() == outcome["group_image_sha256"]
    assert sha256(phone).hexdigest() == outcome["phone_preview_sha256"]
    assert len(models.visual_requests) == 1
    assert models.visual_requests[0].image_bytes == group
    assert models.visual_requests[0].media_type == "image/jpeg"
    with Image.open(BytesIO(group)) as image:
        assert image.format == "JPEG"
        assert image.size == GEOMETRY
    with Image.open(BytesIO(phone)) as image:
        assert image.format == "PNG"
        assert image.size == (390, 693)
    assert str(outcome["group_image"]) in (run_dir / "preview.html").read_text(encoding="utf-8")
    manifest = json.loads((run_dir / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["send_ready"] is False
    assert manifest["poster_region_ocr"] == "not_checked"
    assert manifest["batch_accepted"] is False
    assert manifest["trial_version"] == "daily-news-infographic-local-exact-text-trial-v1"
    for name in ("01-copy-candidate.json", "01-copy-audit-verdict.json"):
        private_diagnostic = run_dir / "private" / name
        assert stat.S_IMODE(private_diagnostic.stat().st_mode) == 0o600
        assert private_diagnostic.stat().st_size < 8 * 1024


def test_evidence_first_copy_uses_only_exact_frozen_claims_for_three_cases() -> None:
    for case in _evidence_first_cases():
        copy = build_evidence_first_copy(case)
        fact = next(item for item in case.claims if item.kind == "external_fact")
        brand = next(item for item in case.claims if item.kind == "brand_statement")
        assert copy.title in fact.text
        assert copy.news_summary == fact.text
        assert copy.news_claim_ids == (fact.claim_id,)
        assert copy.cards[0].kind == "science"
        assert copy.cards[0].heading == "找原文依据"
        assert copy.cards[0].body == f"原文有哪些内容支持“{copy.title}”？请找出对应依据。"
        assert copy.news_summary != copy.cards[0].body
        assert copy.cards[0].claim_ids == (fact.claim_id,)
        assert copy.cards[1].body == "读完这条新闻，你还想了解什么？"
        assert copy.cards[1].claim_ids == (fact.claim_id,)
        assert copy.cards[2].heading in brand.text
        assert copy.cards[2].body == brand.text
        assert copy.cards[2].claim_ids == (brand.claim_id,)
        validate_poster_copy(case, copy)


def test_evidence_first_copy_rejects_unbounded_title_or_brand_heading() -> None:
    payload = deepcopy(package_payload())
    fact = "科学" * 20
    payload["copy"]["claims"][0]["text"] = fact
    payload["sources"][0]["claim_text"] = fact
    payload["sources"][0]["exact_quote"] = fact
    with pytest.raises(InfographicRunError, match="external fact"):
        build_evidence_first_copy(validate_package_snapshot(payload))

    payload = deepcopy(package_payload())
    fact = "科学课鼓励学生观察身边现象，并记录自己提出的问题。"
    brand = "赛先生" * 8
    payload["copy"]["claims"][0]["text"] = fact
    payload["sources"][0]["claim_text"] = fact
    payload["sources"][0]["exact_quote"] = fact
    payload["copy"]["claims"][1]["text"] = brand
    payload["brand_bindings"][0]["claim_text"] = brand
    with pytest.raises(InfographicRunError, match="brand statement"):
        build_evidence_first_copy(validate_package_snapshot(payload))


def test_evidence_first_copy_adds_no_number_beyond_frozen_claim() -> None:
    payload = deepcopy(package_payload())
    fact = "2026年科学教育活动启动，学校将组织学生观察校园植物。"
    payload["copy"]["claims"][0]["text"] = fact
    payload["sources"][0]["claim_text"] = fact
    payload["sources"][0]["exact_quote"] = fact
    copy = build_evidence_first_copy(validate_package_snapshot(payload))
    displayed = (
        copy.title,
        copy.news_summary,
        *(item for card in copy.cards for item in (card.heading, card.body)),
    )
    numbers = {match.group() for text in displayed for match in re.finditer(r"\d+", text)}
    assert numbers == {"2026"}


@pytest.mark.asyncio
async def test_evidence_first_trial_keeps_audit_and_no_copy_model_intent(tmp_path: Path) -> None:
    cases = _evidence_first_cases()
    models = _Models()
    run_dir = tmp_path / "evidence-first"
    summary = await run_local_batch(
        cases,
        run_dir=run_dir,
        models=models,
        references=_reference(),
        exact_text_quality_trial=True,
        evidence_first_copy_trial=True,
    )
    assert len(models.prompts) == 3
    assert all("逐句检查" in prompt for prompt in models.prompts)
    assert not list((run_dir / "private").glob("*-copy.intent.json"))
    assert len(list((run_dir / "private").glob("*-copy-audit.intent.json"))) == 3
    manifest = json.loads((run_dir / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["trial_version"] == "daily-news-infographic-local-evidence-first-trial-v1"
    assert manifest["send_ready"] is False
    assert all(
        item["copy_provenance"] == "frozen_claims_evidence_first_local" for item in summary.cases
    )
    assert all(item["generation"] == "generated" for item in summary.cases)
    assert len(models.image_requests) == 3
    assert len(models.visual_requests) == 3
    assert all(
        request.rubric_version == "daily-news-infographic-visual-v2-evidence-first"
        and "Chinese news poster" in request.criteria[0]
        and "science-news poster" not in " ".join(request.criteria)
        for request in models.visual_requests
    )


@pytest.mark.asyncio
async def test_model_rendered_trial_draws_body_without_overlay_and_stays_unready(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import app.application.services.news_infographic_text_overlay as overlay

    case = _evidence_first_cases()[0]
    copy = build_evidence_first_copy(case)
    prompt = build_model_rendered_image_prompt(case, copy)
    assert all(value in prompt for value in (copy.title, copy.news_summary))
    assert all(card.heading in prompt and card.body in prompt for card in copy.cards)
    assert "胸前蓝色方形徽章" in prompt
    assert "深色空框" in prompt
    assert "由程序写字" not in prompt
    validate_image_generation_request_prompt(
        ImageGenerationRequest(
            run_id=uuid4(),
            draft_version_id=case.draft_version_id,
            prompt=prompt,
            request_fingerprint="model-rendered-preflight",
            unrestricted_prompt_length=True,
        )
    )

    def forbidden_overlay(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("body text overlay must not run")

    monkeypatch.setattr(overlay, "render_exact_text_overlay", forbidden_overlay)
    models = _Models()
    run_dir = tmp_path / "model-rendered"
    summary = await run_local_batch(
        (case,),
        run_dir=run_dir,
        models=models,
        references=_reference(),
        exact_text_quality_trial=True,
        evidence_first_copy_trial=True,
        model_rendered_text_trial=True,
    )
    outcome = summary.cases[0]
    assert len(models.prompts) == 1
    assert len(models.image_requests) == 1
    assert models.image_requests[0].prompt == " ".join(prompt.split())
    assert outcome["body_rendering"] == "model"
    assert outcome["overlay"] == "not_applied"
    assert outcome["body_text_verification"] == "not_checked"
    assert outcome["poster_region_ocr"] == "not_checked"
    assert outcome["ocr"] == "not_checked_region_gate"
    assert outcome["footer"] == "passed"
    assert "composite_image" not in outcome
    assert not list((run_dir / "images").glob("*composite*"))
    assert outcome["footer_source_url_lines"] == []  # 图片上不放链接
    raw = (run_dir / str(outcome["image"])).read_bytes()
    final = (run_dir / str(outcome["group_image"])).read_bytes()
    assert sha256(raw).hexdigest() == outcome["image_sha256"]
    assert sha256(final).hexdigest() == outcome["group_image_sha256"]
    assert models.visual_requests[0].image_bytes == final
    assert (
        models.visual_requests[0].rubric_version
        == "daily-news-infographic-visual-v3-model-rendered"
    )
    manifest = json.loads((run_dir / "manifest.json").read_text(encoding="utf-8"))
    snapshot = json.loads((run_dir / "private" / "01-image-request.json").read_text())
    assert manifest["trial_version"] == "daily-news-infographic-local-model-rendered-trial-v1"
    assert manifest["send_ready"] is False
    assert manifest["batch_accepted"] is False
    assert snapshot["schema_version"] == "daily-news-infographic-model-rendered-prompt-v1"
    assert snapshot["body_rendering"] == "model"
    assert snapshot["request_fingerprint"] == models.image_requests[0].request_fingerprint
    assert not list((run_dir / "private").glob("*-copy.intent.json"))


def test_model_rendered_prompt_excludes_unbound_topic_title() -> None:
    case = _evidence_first_cases()[0].model_copy(
        update={"topic_title": "未绑定的实验已经证明孩子成绩提升"}
    )
    prompt = build_model_rendered_image_prompt(case, build_evidence_first_copy(case))
    assert case.topic_title not in prompt
    assert "已绑定" in prompt


def test_model_rendered_cli_flag_is_explicit() -> None:
    args = local_main._parser().parse_args(
        [
            "run",
            "--input-bundle",
            "/tmp/frozen.json",
            "--output-dir",
            "/tmp/fresh",
            "--execute",
            "--exact-text-quality-trial",
            "--evidence-first-copy-trial",
            "--model-rendered-text-trial",
        ]
    )
    assert args.model_rendered_text_trial is True
    assert args.reference_style_trial is False
    assert args.exact_text_quality_trial is True
    assert args.evidence_first_copy_trial is True


def _reviewed_cards(case: ValidatedInfographicInput) -> ReviewedPosterCards:
    fact = next(claim for claim in case.claims if claim.kind == "external_fact")
    brand = next(claim for claim in case.claims if claim.kind == "brand_statement")
    return ReviewedPosterCards(
        schema_version="daily-news-infographic-reviewed-cards-v1",
        package_id=case.package_id,
        input_fingerprint=case.fingerprint,
        cards=(
            PosterCard(
                kind="science",
                heading="新闻提出什么？",
                body=f"新闻原文写道：{fact.text}",
                claim_ids=(fact.claim_id,),
            ),
            PosterCard(
                kind="learning",
                heading="怎样核对？",
                body="先问依据是什么，再从原文找证据。",
                claim_ids=(fact.claim_id,),
            ),
            PosterCard(
                kind="brand",
                heading="赛先生鼓励孩子提问",
                body=brand.text,
                claim_ids=(brand.claim_id,),
            ),
        ),
    )


def test_reviewed_cards_change_only_three_cards_and_reject_unbound_edits() -> None:
    case = _evidence_first_cases()[0]
    reviewed = _reviewed_cards(case)
    base = build_evidence_first_copy(case)
    copy = build_reviewed_card_copy(case, reviewed)
    assert copy.title == base.title
    assert copy.news_summary == base.news_summary
    assert copy.news_claim_ids == base.news_claim_ids
    assert copy.cards == reviewed.cards
    assert copy.cards != base.cards
    with pytest.raises(InfographicRunError, match="do not match"):
        build_reviewed_card_copy(case, reviewed.model_copy(update={"input_fingerprint": "0" * 64}))
    unsupported = reviewed.model_copy(
        update={
            "cards": (
                reviewed.cards[0].model_copy(update={"body": "这项新研究已经证明孩子成绩提高。"}),
                *reviewed.cards[1:],
            )
        }
    )
    with pytest.raises(InfographicRunError, match="must quote a cited external fact"):
        build_reviewed_card_copy(case, unsupported)
    wrong_brand = reviewed.model_copy(
        update={
            "cards": (
                *reviewed.cards[:2],
                reviewed.cards[2].model_copy(update={"body": "我们保证孩子成绩提高。"}),
            )
        }
    )
    with pytest.raises(InfographicRunError, match="must quote a cited brand statement"):
        build_reviewed_card_copy(case, wrong_brand)


@pytest.mark.asyncio
async def test_reviewed_cards_trial_has_new_identity_and_keeps_independent_audit(
    tmp_path: Path,
) -> None:
    case = _evidence_first_cases()[0]
    reviewed = _reviewed_cards(case)
    copy = build_reviewed_card_copy(case, reviewed)
    prompt = build_model_rendered_image_prompt(
        case, copy, reference_style_trial=True, reviewed_cards_trial=True
    )
    assert all(card.heading in prompt and card.body in prompt for card in copy.cards)
    assert "画面新闻事实仅限以下已绑定新闻摘要与事实卡引用的外部事实" in prompt
    assert case.claims[0].text in prompt
    old_prompt = build_model_rendered_image_prompt(
        case, build_evidence_first_copy(case), reference_style_trial=True
    )
    assert "画面事实范围仅限以下已绑定新闻摘要" in old_prompt
    assert "画面新闻事实仅限以下已绑定新闻摘要与事实卡引用的外部事实" not in old_prompt
    models = _Models()
    run_dir = tmp_path / "reviewed"
    summary = await run_local_batch(
        (case,),
        run_dir=run_dir,
        models=models,
        references=_style_reference(),
        exact_text_quality_trial=True,
        evidence_first_copy_trial=True,
        model_rendered_text_trial=True,
        reference_style_trial=True,
        reviewed_cards=reviewed,
    )
    assert summary.cases[0]["copy"] == "accepted"
    assert summary.cases[0]["copy_provenance"] == "reviewed_claim_bound_cards_local"
    assert len(models.prompts) == len(models.image_requests) == 1
    manifest = json.loads((run_dir / "manifest.json").read_text())
    snapshot = json.loads((run_dir / "private" / "01-image-request.json").read_text())
    assert manifest["trial_version"] == "daily-news-infographic-local-reviewed-cards-trial-v1"
    assert manifest["prompt_version"] == "daily-news-infographic-reviewed-cards-prompt-v1"
    assert manifest["send_ready"] is False
    assert snapshot["copy"] == copy.model_dump(mode="json")
    assert snapshot["schema_version"] == manifest["prompt_version"]
    assert snapshot["request_fingerprint"] == models.image_requests[0].request_fingerprint
    assert (
        models.visual_requests[0].rubric_version
        == "daily-news-infographic-visual-v5-reviewed-cards"
    )
    assert (run_dir / "private" / "01-copy-audit.intent.json").is_file()
    assert (run_dir / "private" / "01-image.intent.json").is_file()
    assert not (run_dir / "private" / "01-copy.intent.json").exists()
    old_models = _Models()
    await run_local_batch(
        (case,),
        run_dir=tmp_path / "old-reference",
        models=old_models,
        references=_style_reference(),
        exact_text_quality_trial=True,
        evidence_first_copy_trial=True,
        model_rendered_text_trial=True,
        reference_style_trial=True,
    )
    assert (
        models.image_requests[0].request_fingerprint
        != old_models.image_requests[0].request_fingerprint
    )


@pytest.mark.asyncio
async def test_reviewed_cards_v2_versions_are_distinct_even_for_same_claim_bound_copy(
    tmp_path: Path,
) -> None:
    case = _evidence_first_cases()[0]
    first = _reviewed_cards(case)
    second = first.model_copy(update={"schema_version": "daily-news-infographic-reviewed-cards-v2"})
    models_v1 = _Models()
    models_v2 = _Models()
    first_dir = tmp_path / "reviewed-v1"
    second_dir = tmp_path / "reviewed-v2"
    trial = {
        "exact_text_quality_trial": True,
        "evidence_first_copy_trial": True,
        "model_rendered_text_trial": True,
        "reference_style_trial": True,
    }
    await run_local_batch(
        (case,),
        run_dir=first_dir,
        models=models_v1,
        references=_style_reference(),
        reviewed_cards=first,
        **trial,
    )
    await run_local_batch(
        (case,),
        run_dir=second_dir,
        models=models_v2,
        references=_style_reference(),
        reviewed_cards=second,
        **trial,
    )
    manifest = json.loads((second_dir / "manifest.json").read_text())
    snapshot = json.loads((second_dir / "private" / "01-image-request.json").read_text())
    assert manifest["trial_version"] == "daily-news-infographic-local-reviewed-cards-trial-v2"
    assert manifest["prompt_version"] == "daily-news-infographic-reviewed-cards-prompt-v2"
    assert manifest["copy_policy_version"] == "daily-news-infographic-reviewed-cards-copy-v2"
    assert snapshot["trial_version"] == manifest["trial_version"]
    assert snapshot["schema_version"] == manifest["prompt_version"]
    assert (
        models_v2.visual_requests[0].rubric_version
        == "daily-news-infographic-visual-v6-reviewed-cards"
    )
    assert (
        models_v1.image_requests[0].request_fingerprint
        != models_v2.image_requests[0].request_fingerprint
    )
    assert (second_dir / "private" / "01-copy-audit.intent.json").is_file()
    assert (second_dir / "private" / "01-image.intent.json").is_file()


async def _manual_retry_parent(
    tmp_path: Path,
) -> tuple[ValidatedInfographicInput, ReviewedPosterCards, Path, _Models]:
    case = _evidence_first_cases()[0]
    reviewed = _reviewed_cards(case).model_copy(
        update={"schema_version": "daily-news-infographic-reviewed-cards-v2"}
    )
    output_root = tmp_path / "output"
    output_root.mkdir()
    prior_dir = output_root / "reviewed-v2-unknown"
    models = _Models(fail_image="unavailable")
    models.image_model = "gpt-image-2.5-sunburst"
    await run_local_batch(
        (case,),
        run_dir=prior_dir,
        models=models,
        references=_style_reference(),
        exact_text_quality_trial=True,
        evidence_first_copy_trial=True,
        model_rendered_text_trial=True,
        reference_style_trial=True,
        reviewed_cards=reviewed,
    )
    return case, reviewed, prior_dir, models


@pytest.mark.asyncio
async def test_manual_image_retry_uses_accepted_copy_once_and_new_attempt_identity(
    tmp_path: Path,
) -> None:
    case, reviewed, prior_dir, parent_models = await _manual_retry_parent(tmp_path)
    assert len(parent_models.prompts) == 1
    output_dir = prior_dir.parent / "manual-retry"
    copy, retry = local_main._verified_manual_image_retry(
        prior_dir,
        output_dir,
        prior_dir.parent,
        case,
        reviewed,
        _style_reference(),
        parent_models.copy_model,
    )
    models = _Models()
    models.image_model = "gpt-image-2.5-sunburst"
    summary = await run_local_batch(
        (case,),
        run_dir=output_dir,
        models=models,
        references=_style_reference(),
        accepted_copy=copy,
        exact_text_quality_trial=True,
        evidence_first_copy_trial=True,
        model_rendered_text_trial=True,
        reference_style_trial=True,
        reviewed_cards=reviewed,
        manual_image_retry=retry,
    )
    assert models.prompts == []
    assert len(models.image_requests) == 1
    assert summary.cases[0]["copy"] == "reused_accepted"
    assert summary.cases[0]["copy_provenance"] == "prior_reviewed_v2_manual_image_retry"
    assert summary.cases[0]["group_image_sha256"]
    assert (output_dir / summary.cases[0]["group_image"]).is_file()
    parent_request = json.loads((prior_dir / "private/01-image-request.json").read_text())
    request = json.loads((output_dir / "private/01-image-request.json").read_text())
    manifest = json.loads((output_dir / "manifest.json").read_text())
    assert request["prompt"] == parent_request["prompt"]
    assert request["copy"] == parent_request["copy"]
    assert request["references"] == parent_request["references"]
    assert request["request_fingerprint"] != parent_request["request_fingerprint"]
    assert models.image_requests[0].provider_request_fingerprint == request["request_fingerprint"]
    assert request["manual_retry_parent_fingerprint"] == parent_request["request_fingerprint"]
    assert manifest["send_ready"] is False
    assert (
        manifest["trial_version"] == "daily-news-infographic-reviewed-cards-manual-image-retry-v1"
    )
    assert not (output_dir / "private/01-copy-audit.intent.json").exists()
    assert (
        prior_dir.parent
        / f".manual-image-retry-{parent_request['request_fingerprint']}.intent.json"
    ).is_file()
    duplicate_models = _Models()
    duplicate_models.image_model = "gpt-image-2.5-sunburst"
    with pytest.raises(InfographicRunError, match="already reserved"):
        await run_local_batch(
            (case,),
            run_dir=prior_dir.parent / "another-directory",
            models=duplicate_models,
            references=_style_reference(),
            accepted_copy=copy,
            exact_text_quality_trial=True,
            evidence_first_copy_trial=True,
            model_rendered_text_trial=True,
            reference_style_trial=True,
            reviewed_cards=reviewed,
            manual_image_retry=retry,
        )


@pytest.mark.asyncio
async def test_manual_image_retry_rejects_prior_tampering_without_new_intent(
    tmp_path: Path,
) -> None:
    case, reviewed, prior_dir, parent_models = await _manual_retry_parent(tmp_path)
    audit_path = prior_dir / "private/01-copy-audit-verdict.json"
    audit = json.loads(audit_path.read_text())
    audit["accepted"] = False
    audit_path.write_text(json.dumps(audit))
    output_dir = prior_dir.parent / "should-not-exist"
    with pytest.raises(ValueError, match="copy, audit or news identity"):
        local_main._verified_manual_image_retry(
            prior_dir,
            output_dir,
            prior_dir.parent,
            case,
            reviewed,
            _style_reference(),
            parent_models.copy_model,
        )
    assert not output_dir.exists()
    assert not list(prior_dir.parent.glob(".manual-image-retry-*.intent.json"))


@pytest.mark.asyncio
async def test_manual_image_retry_rejects_unbound_audit_intent(tmp_path: Path) -> None:
    case, reviewed, prior_dir, parent_models = await _manual_retry_parent(tmp_path)
    intent_path = prior_dir / "private/01-copy-audit.intent.json"
    intent = json.loads(intent_path.read_text())
    intent["request_fingerprint"] = "0" * 64
    intent_path.write_text(json.dumps(intent))
    output_dir = prior_dir.parent / "should-not-exist"
    with pytest.raises(ValueError, match="copy, audit or news identity"):
        local_main._verified_manual_image_retry(
            prior_dir,
            output_dir,
            prior_dir.parent,
            case,
            reviewed,
            _style_reference(),
            parent_models.copy_model,
        )
    assert not output_dir.exists()
    assert not list(prior_dir.parent.glob(".manual-image-retry-*.intent.json"))


def test_manual_image_retry_confines_output_to_project_workspace(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(local_main, "_WORKSPACE_ROOT", tmp_path)
    (tmp_path / "output").mkdir()
    assert local_main._manual_retry_output_root(tmp_path) == tmp_path / "output"
    other = tmp_path / "other"
    other.mkdir()
    with pytest.raises(ValueError, match="project workspace"):
        local_main._manual_retry_output_root(other)


@pytest.mark.asyncio
async def test_manual_image_retry_rejects_changed_prompt_or_model_before_lock(
    tmp_path: Path,
) -> None:
    case, reviewed, prior_dir, parent_models = await _manual_retry_parent(tmp_path)
    copy, retry = local_main._verified_manual_image_retry(
        prior_dir,
        prior_dir.parent / "retry",
        prior_dir.parent,
        case,
        reviewed,
        _style_reference(),
        parent_models.copy_model,
    )
    changed = ManualImageRetry(
        parent_request_fingerprint=retry.parent_request_fingerprint,
        parent_run_name=retry.parent_run_name,
        frozen_prompt=retry.frozen_prompt + " 变化",
        model=retry.model,
    )
    models = _Models()
    models.image_model = "gpt-image-2.5-sunburst"
    with pytest.raises(InfographicRunError, match="parent request identity differs"):
        await run_local_batch(
            (case,),
            run_dir=prior_dir.parent / "retry",
            models=models,
            references=_style_reference(),
            accepted_copy=copy,
            exact_text_quality_trial=True,
            evidence_first_copy_trial=True,
            model_rendered_text_trial=True,
            reference_style_trial=True,
            reviewed_cards=reviewed,
            manual_image_retry=changed,
        )
    assert not (prior_dir.parent / "retry").exists()
    assert not list(prior_dir.parent.glob(".manual-image-retry-*.intent.json"))


def test_worldskills_reviewed_cards_v2_quotes_only_locked_claims() -> None:
    path = (
        Path(__file__).resolve().parents[1]
        / "fixtures/news_infographic/worldskills_reviewed_cards_v2.json"
    )
    reviewed = local_main._read_reviewed_cards(path)
    assert reviewed.schema_version == "daily-news-infographic-reviewed-cards-v2"
    assert reviewed.cards[0].body == (
        "国务院总理李强9月23日上午在上海出席2026年世界技能大会开幕式并致辞。"
    )
    assert reviewed.cards[0].claim_ids == ("claim-1",)
    assert reviewed.cards[1].claim_ids == ("claim-2",)
    assert reviewed.cards[1].heading == "AI通识学什么？"
    assert reviewed.cards[1].body == (
        "“人工智能通识教育”具体学什么？它怎样帮助劳动者实现“技能转型”？"
    )
    assert reviewed.cards[2].heading == "不直接把答案塞给孩子"
    assert reviewed.cards[2].body == "我们的目标是让孩子学会质疑，而不是被动接受。"
    assert reviewed.cards[2].claim_ids == ("claim-3", "claim-4")


@pytest.mark.asyncio
async def test_reviewed_cards_audit_rejection_reserves_no_image(tmp_path: Path) -> None:
    class RejectingAudit(_Models):
        async def complete_json(self, prompt: str) -> dict[str, object]:
            self.prompts.append(prompt)
            return {"accepted": False, "issues": ["unsupported_claim"]}

    case = _evidence_first_cases()[0]
    models = RejectingAudit()
    run_dir = tmp_path / "reviewed-rejected"
    summary = await run_local_batch(
        (case,),
        run_dir=run_dir,
        models=models,
        references=_style_reference(),
        exact_text_quality_trial=True,
        evidence_first_copy_trial=True,
        model_rendered_text_trial=True,
        reference_style_trial=True,
        reviewed_cards=_reviewed_cards(case),
    )
    assert summary.cases[0]["reason_code"] == "copy_audit_rejected"
    assert (run_dir / "private" / "01-copy-audit.intent.json").is_file()
    assert not (run_dir / "private" / "01-image.intent.json").exists()
    assert not models.image_requests


@pytest.mark.asyncio
async def test_reviewed_cards_cli_requires_reference_style_before_loading_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    case = _evidence_first_cases()[0]
    monkeypatch.setattr(local_main, "read_frozen_input_bundle", lambda _path: (case,))
    args = local_main._parser().parse_args(
        [
            "run",
            "--input-bundle",
            str(tmp_path / "input.json"),
            "--output-dir",
            str(tmp_path / "no-output"),
            "--execute",
            "--reviewed-cards-json",
            str(tmp_path / "missing.json"),
        ]
    )
    with pytest.raises(ValueError, match="reviewed cards require reference-style trial"):
        await local_main._run(args)
    assert not (tmp_path / "no-output").exists()


def test_reviewed_cards_reader_is_bounded_and_rejects_duplicate_keys(tmp_path: Path) -> None:
    duplicate = tmp_path / "duplicate.json"
    duplicate.write_text('{"schema_version":"x","schema_version":"y"}', encoding="utf-8")
    with pytest.raises(ValueError, match="duplicate JSON keys"):
        local_main._read_reviewed_cards(duplicate)
    large = tmp_path / "large.json"
    large.write_text("x" * 4097, encoding="utf-8")
    with pytest.raises(ValueError, match="bounded regular file"):
        local_main._read_reviewed_cards(large)
    link = tmp_path / "link.json"
    link.symlink_to(duplicate)
    with pytest.raises(ValueError, match="unsafe"):
        local_main._read_reviewed_cards(link)


@pytest.mark.asyncio
async def test_reference_style_cli_requires_explicit_modes_before_loading_assets(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    case = _evidence_first_cases()[0]
    monkeypatch.setattr(local_main, "read_frozen_input_bundle", lambda _path: (case,))
    args = local_main._parser().parse_args(
        [
            "run",
            "--input-bundle",
            str(tmp_path / "input.json"),
            "--output-dir",
            str(tmp_path / "no-output"),
            "--execute",
            "--reference-style-trial",
        ]
    )
    with pytest.raises(ValueError, match="reference-style requires"):
        await local_main._run(args)
    assert not (tmp_path / "no-output").exists()


@pytest.mark.asyncio
async def test_reference_style_trial_uses_two_refs_and_distinct_non_sendable_identity(
    tmp_path: Path,
) -> None:
    case = _evidence_first_cases()[0]
    copy = build_evidence_first_copy(case)
    prompt = build_model_rendered_image_prompt(case, copy, reference_style_trial=True)
    assert "第二张参考图" in prompt
    assert "绝对不要复制旧粮食新闻" in prompt
    assert "y1858–2048" in prompt
    assert all(card.heading in prompt and card.body in prompt for card in copy.cards)
    assert case.topic_title not in prompt
    validate_image_generation_request_prompt(
        ImageGenerationRequest(
            run_id=uuid4(),
            draft_version_id=case.draft_version_id,
            prompt=prompt,
            request_fingerprint="reference-style-preflight",
            unrestricted_prompt_length=True,
        )
    )
    models = _Models()
    style_run = tmp_path / "reference-style"
    summary = await run_local_batch(
        (case,),
        run_dir=style_run,
        models=models,
        references=_style_reference(),
        exact_text_quality_trial=True,
        evidence_first_copy_trial=True,
        model_rendered_text_trial=True,
        reference_style_trial=True,
    )
    assert summary.batch_accepted is False
    assert len(models.image_requests) == 1
    assert tuple(ref.role for ref in models.image_requests[0].references) == (
        "approved-characters",
        "approved-style",
    )
    assert models.image_requests[0].prompt == " ".join(prompt.split())
    assert len(models.visual_requests) == 1
    assert (
        models.visual_requests[0].rubric_version
        == "daily-news-infographic-visual-v4-reference-style"
    )
    assert "three" in " ".join(models.visual_requests[0].criteria)
    assert all(len(criterion) <= 200 for criterion in models.visual_requests[0].criteria)
    assert "historical grain text" in " ".join(models.visual_requests[0].criteria)
    manifest = json.loads((style_run / "manifest.json").read_text())
    snapshot = json.loads((style_run / "private" / "01-image-request.json").read_text())
    assert manifest["trial_version"] == "daily-news-infographic-local-reference-style-trial-v1"
    assert manifest["prompt_version"] == "daily-news-infographic-reference-style-prompt-v1"
    assert manifest["send_ready"] is False
    assert manifest["batch_accepted"] is False
    assert snapshot["schema_version"] == "daily-news-infographic-reference-style-prompt-v1"
    assert [item["role"] for item in snapshot["references"]] == [
        "approved-characters",
        "approved-style",
    ]
    assert snapshot["request_fingerprint"] == models.image_requests[0].request_fingerprint
    assert (style_run / "private" / "01-image.intent.json").is_file()
    assert not list((style_run / "private").glob("*-copy.intent.json"))
    assert not list(style_run.glob("*send*"))

    old_models = _Models()
    await run_local_batch(
        (case,),
        run_dir=tmp_path / "old-model-rendered",
        models=old_models,
        references=_reference(),
        exact_text_quality_trial=True,
        evidence_first_copy_trial=True,
        model_rendered_text_trial=True,
    )
    assert (
        models.image_requests[0].request_fingerprint
        != old_models.image_requests[0].request_fingerprint
    )


@pytest.mark.asyncio
async def test_reference_style_trial_rejects_missing_flags_or_wrong_refs_before_intent(
    tmp_path: Path,
) -> None:
    case = _evidence_first_cases()[0]
    models = _Models()
    with pytest.raises(InfographicRunError, match="reference-style requires"):
        await run_local_batch(
            (case,),
            run_dir=tmp_path / "missing-model-mode",
            models=models,
            references=_style_reference(),
            exact_text_quality_trial=True,
            evidence_first_copy_trial=True,
            reference_style_trial=True,
        )
    with pytest.raises(InfographicRunError, match="approved reference roles"):
        await run_local_batch(
            (case,),
            run_dir=tmp_path / "wrong-reference-set",
            models=models,
            references=_reference(),
            exact_text_quality_trial=True,
            evidence_first_copy_trial=True,
            model_rendered_text_trial=True,
            reference_style_trial=True,
        )
    assert not (tmp_path / "missing-model-mode").exists()
    assert not (tmp_path / "wrong-reference-set").exists()
    assert not models.image_requests


@pytest.mark.asyncio
async def test_model_rendered_unknown_preserves_one_intent_without_replay(tmp_path: Path) -> None:
    case = _evidence_first_cases()[0]
    models = _Models(fail_image="timeout")
    run_dir = tmp_path / "model-unknown"
    kwargs = {
        "run_dir": run_dir,
        "models": models,
        "references": _reference(),
        "exact_text_quality_trial": True,
        "evidence_first_copy_trial": True,
        "model_rendered_text_trial": True,
    }
    summary = await run_local_batch((case,), **kwargs)
    assert summary.cases[0]["generation"] == "result_unknown"
    assert summary.cases[0]["body_text_verification"] == "not_checked"
    assert summary.batch_accepted is False
    assert len(models.image_requests) == 1
    assert (run_dir / "private" / "01-image.intent.json").is_file()
    with pytest.raises(FileExistsError):
        await run_local_batch((case,), **kwargs)
    assert len(models.image_requests) == 1


@pytest.mark.asyncio
async def test_model_rendered_trial_has_distinct_intent_from_overlay_trial(tmp_path: Path) -> None:
    case = _evidence_first_cases()[0]
    overlay_models = _Models()
    model_text_models = _Models()
    overlay = await run_local_batch(
        (case,),
        run_dir=tmp_path / "overlay",
        models=overlay_models,
        references=_reference(),
        exact_text_quality_trial=True,
        evidence_first_copy_trial=True,
    )
    model_text = await run_local_batch(
        (case,),
        run_dir=tmp_path / "model-text",
        models=model_text_models,
        references=_reference(),
        exact_text_quality_trial=True,
        evidence_first_copy_trial=True,
        model_rendered_text_trial=True,
    )
    assert overlay.cases[0]["overlay"] == "passed"
    assert model_text.cases[0]["overlay"] == "not_applied"
    assert (
        overlay_models.image_requests[0].request_fingerprint
        != model_text_models.image_requests[0].request_fingerprint
    )


@pytest.mark.asyncio
async def test_model_rendered_trial_requires_explicit_frozen_fresh_mode(tmp_path: Path) -> None:
    case = _evidence_first_cases()[0]
    models = _Models()
    with pytest.raises(InfographicRunError, match="model-rendered text requires"):
        await run_local_batch(
            (case,),
            run_dir=tmp_path / "missing-opt-in",
            models=models,
            references=_reference(),
            model_rendered_text_trial=True,
        )
    assert not (tmp_path / "missing-opt-in").exists()
    assert not models.image_requests


@pytest.mark.asyncio
async def test_evidence_first_audit_rejection_stops_image(tmp_path: Path) -> None:
    class RejectingAudit(_Models):
        async def complete_json(self, prompt: str) -> dict[str, object]:
            self.prompts.append(prompt)
            return {"accepted": False, "issues": ["unsupported_claim"]}

    models = RejectingAudit()
    run_dir = tmp_path / "evidence-rejected"
    summary = await run_local_batch(
        (_evidence_first_cases()[0],),
        run_dir=run_dir,
        models=models,
        references=_reference(),
        exact_text_quality_trial=True,
        evidence_first_copy_trial=True,
    )
    assert summary.cases[0]["reason_code"] == "copy_audit_rejected"
    assert not models.image_requests
    assert not (run_dir / "private" / "01-copy.intent.json").exists()
    assert not (run_dir / "private" / "01-image.intent.json").exists()


def test_evidence_first_cli_flag_is_explicit() -> None:
    parser = local_main._parser()
    args = parser.parse_args(
        [
            "run",
            "--input-bundle",
            "/tmp/frozen.json",
            "--output-dir",
            "/tmp/fresh",
            "--execute",
            "--evidence-first-copy-trial",
        ]
    )
    assert args.evidence_first_copy_trial is True
    assert args.exact_text_quality_trial is False


@pytest.mark.asyncio
async def test_evidence_first_rejects_non_quality_or_prior_copy_reuse(tmp_path: Path) -> None:
    case = _evidence_first_cases()[0]
    models = _Models()
    with pytest.raises(InfographicRunError, match="fresh exact-text trial"):
        await run_local_batch(
            (case,),
            run_dir=tmp_path / "invalid-default",
            models=models,
            references=_reference(),
            evidence_first_copy_trial=True,
        )
    with pytest.raises(InfographicRunError, match="fresh exact-text trial"):
        await run_local_batch(
            (case,),
            run_dir=tmp_path / "invalid-reuse",
            models=models,
            references=_reference(),
            accepted_copy=build_evidence_first_copy(case),
            exact_text_quality_trial=True,
            evidence_first_copy_trial=True,
        )
    assert not models.prompts
    assert not (tmp_path / "invalid-default").exists()
    assert not (tmp_path / "invalid-reuse").exists()


@pytest.mark.asyncio
async def test_exact_text_quality_trial_layout_failure_reserves_no_image_intent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.application.services.news_infographic_text_overlay import TextOverlayError

    case = validate_package_snapshot(package_payload())
    models = _Models()

    def fail_layout(_copy: PosterCopy, *, use_reviewed_lines: bool) -> tuple[str, tuple[int, ...]]:
        assert use_reviewed_lines is False
        raise TextOverlayError("copy does not fit")

    monkeypatch.setattr(
        "app.application.services.news_infographic_text_overlay.preflight_text_overlay_layout",
        fail_layout,
    )
    run_dir = tmp_path / "no-image"
    summary = await run_local_batch(
        (case,),
        run_dir=run_dir,
        models=models,
        references=_reference(),
        exact_text_quality_trial=True,
    )
    assert summary.cases[0]["generation"] == "blocked_preflight"
    assert summary.cases[0]["reason_code"] == "text_layout_unavailable"
    assert not models.image_requests
    assert not (run_dir / "private" / "01-image.intent.json").exists()


@pytest.mark.asyncio
async def test_exact_text_trial_rejects_schema_valid_but_measured_too_wide_copy_before_image(
    tmp_path: Path,
) -> None:
    case = validate_package_snapshot(package_payload())

    class WideTitleModels(_Models):
        async def complete_json(self, prompt: str) -> dict[str, object]:
            self.prompts.append(prompt)
            if "逐句检查" in prompt:
                return {"accepted": True, "issues": []}
            candidate = _copy_payload()
            candidate["title"] = "长" * 32  # Schema-valid, too wide for two real 51px Noto lines.
            candidate["cards"][0]["heading"] = "科" * 14
            return candidate

    models = WideTitleModels()
    run_dir = tmp_path / "measured-too-wide"
    summary = await run_local_batch(
        (case,),
        run_dir=run_dir,
        models=models,
        references=_reference(),
        exact_text_quality_trial=True,
    )
    assert summary.cases[0]["copy"] == "accepted"
    assert summary.cases[0]["generation"] == "blocked_preflight"
    assert summary.cases[0]["reason_code"] == "text_layout_unavailable"
    assert len(models.prompts) == 2
    assert not models.image_requests
    assert not (run_dir / "private" / "01-image.intent.json").exists()


@pytest.mark.asyncio
async def test_exact_text_quality_trial_oversize_group_asset_is_not_ready(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    case = validate_package_snapshot(package_payload())
    models = _Models()

    def fail_group(_body: bytes, *, max_bytes: int) -> bytes:
        assert max_bytes == 2 * 1024 * 1024
        raise ValueError("too large")

    monkeypatch.setattr(
        "app.application.services.wecom_news_infographic.prepare_infographic_group_jpeg",
        fail_group,
    )
    run_dir = tmp_path / "oversize-group"
    summary = await run_local_batch(
        (case,),
        run_dir=run_dir,
        models=models,
        references=_reference(),
        exact_text_quality_trial=True,
    )
    assert len(models.image_requests) == 1
    assert summary.cases[0]["group_jpeg"] == "failed"
    assert summary.cases[0]["reason_code"] == "group_jpeg_unavailable"
    assert "group_image_sha256" not in summary.cases[0]
    assert summary.batch_accepted is False


@pytest.mark.asyncio
async def test_exact_text_quality_trial_rejects_corrupt_group_before_saving(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    case = validate_package_snapshot(package_payload())
    models = _Models()
    monkeypatch.setattr(
        "app.application.services.wecom_news_infographic.prepare_infographic_group_jpeg",
        lambda _body, *, max_bytes: b"not-a-jpeg",
    )
    run_dir = tmp_path / "corrupt-group"
    summary = await run_local_batch(
        (case,),
        run_dir=run_dir,
        models=models,
        references=_reference(),
        exact_text_quality_trial=True,
    )
    assert summary.cases[0]["group_jpeg"] == "failed"
    assert not list((run_dir / "images").glob("*-group.jpg"))
    assert not models.ocr_requests


def test_cli_exact_text_trial_is_explicit_and_reference_override_is_scoped() -> None:
    parser = local_main._parser()
    base = ["run", "--input-bundle", "input.json", "--output-dir", "fresh", "--execute"]
    default = parser.parse_args(base)
    assert default.exact_text_quality_trial is False
    assert default.approved_asset_root is None
    trial = parser.parse_args(
        [*base, "--exact-text-quality-trial", "--approved-asset-root", "/tmp/assets"]
    )
    assert trial.exact_text_quality_trial is True
    assert trial.approved_asset_root == Path("/tmp/assets")


def test_exact_text_trial_uses_only_pinned_formal_character_reference(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import app.application.services.wecom_news_infographic as production

    character_path = tmp_path / local_main._CHARACTER_REFERENCE.relative_to(
        local_main._PROJECT_ROOT
    )
    sample_path = tmp_path / local_main._APPROVED_SAMPLE.relative_to(local_main._PROJECT_ROOT)
    character_path.parent.mkdir(parents=True)
    sample_path.parent.mkdir(parents=True)
    character = _png((10, 10))
    character_path.write_bytes(character)
    sample_path.write_bytes(_png((11, 11)))
    monkeypatch.setattr(production, "_APPROVED_CHARACTER_SHA256", sha256(character).hexdigest())

    trial = local_main._approved_references(asset_root=tmp_path, exact_text_quality_trial=True)
    assert trial == production._approved_reference(asset_root=tmp_path)
    assert len(trial) == 1
    assert trial[0].role == "approved-characters"
    assert trial[0].sha256 == sha256(character).hexdigest()
    assert len(local_main._approved_references(asset_root=tmp_path)) == 2
    monkeypatch.setattr(production, "_REFERENCE_ROOT", tmp_path)
    monkeypatch.setattr(production, "_REFERENCE_PATH", character_path)
    assert production._approved_reference() == trial

    character_path.write_bytes(_png((12, 12)))
    with pytest.raises(ValueError, match="approved character reference is invalid"):
        local_main._approved_references(asset_root=tmp_path, exact_text_quality_trial=True)


def test_reference_style_loader_pins_both_local_assets(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import app.application.services.wecom_news_infographic as production

    character_path = tmp_path / local_main._CHARACTER_REFERENCE.relative_to(
        local_main._PROJECT_ROOT
    )
    sample_path = tmp_path / local_main._APPROVED_SAMPLE.relative_to(local_main._PROJECT_ROOT)
    character_path.parent.mkdir(parents=True)
    sample_path.parent.mkdir(parents=True)
    character = _png((10, 10))
    style = _png((11, 11))
    character_path.write_bytes(character)
    sample_path.write_bytes(style)
    monkeypatch.setattr(production, "_APPROVED_CHARACTER_SHA256", sha256(character).hexdigest())
    monkeypatch.setattr(local_main, "_APPROVED_STYLE_SHA256", sha256(style).hexdigest())

    references = local_main._approved_references(
        asset_root=tmp_path, exact_text_quality_trial=True, reference_style_trial=True
    )
    assert tuple(item.role for item in references) == ("approved-characters", "approved-style")
    assert tuple(item.sha256 for item in references) == (
        sha256(character).hexdigest(),
        sha256(style).hexdigest(),
    )
    sample_path.write_bytes(_png((12, 12)))
    with pytest.raises(ValueError, match="approved reference-style assets have changed"):
        local_main._approved_references(
            asset_root=tmp_path, exact_text_quality_trial=True, reference_style_trial=True
        )
    with pytest.raises(ValueError, match="requires exact-text"):
        local_main._approved_references(asset_root=tmp_path, reference_style_trial=True)


@pytest.mark.asyncio
async def test_exact_text_trial_rejects_extra_reference_before_creating_run(
    tmp_path: Path,
) -> None:
    case = validate_package_snapshot(package_payload())
    models = _Models()
    run_dir = tmp_path / "bad-references"
    with pytest.raises(ValueError, match="formal character reference only"):
        await run_local_batch(
            (case,),
            run_dir=run_dir,
            models=models,
            references=(*_reference(), *_reference()),
            exact_text_quality_trial=True,
        )
    assert not run_dir.exists()
    assert not models.prompts


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["timeout", "503", "square", "corrupt"])
async def test_exact_text_trial_first_portrait_failure_stops_remaining_image_calls(
    tmp_path: Path, failure: str
) -> None:
    first = validate_package_snapshot(package_payload())
    second = first.model_copy(
        update={
            "package_id": first.copy_generation_run_id,
            "selected_event_version_id": first.selected_event_id,
        }
    )
    models = _Models(fail_image=failure)
    run_dir = tmp_path / "failed-first-portrait"
    summary = await run_local_batch(
        (first, second),
        run_dir=run_dir,
        models=models,
        references=_reference(),
        exact_text_quality_trial=True,
    )
    assert len(models.image_requests) == 1
    assert summary.cases[0]["generation"] in {"result_unknown", "generated_invalid"}
    assert summary.cases[1]["generation"] == "skipped_after_first_portrait_gate"
    assert (run_dir / "private" / "01-image.intent.json").is_file()
    assert not (run_dir / "private" / "02-image.intent.json").exists()
    assert summary.batch_accepted is False


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("failure", "reason", "state"),
    [
        (ImageProviderTimeoutError(), "image_provider_timeout", "result_unknown"),
        (ProviderTimeoutError(), "image_provider_timeout", "result_unknown"),
        (ProviderUnavailableError(), "image_provider_unavailable", "result_unknown"),
        (ProviderRateLimitError(), "image_provider_rate_limited", "result_unknown"),
        (
            ProviderAuthenticationError(),
            "image_provider_authentication_failed",
            "result_unknown",
        ),
        (ImageProviderQuotaError(), "image_provider_quota_exhausted", "result_unknown"),
        (ImageProviderConfigurationError(), "image_provider_not_configured", "result_unknown"),
        (ProviderInputLimitError(), "image_provider_input_limit", "result_unknown"),
        (ProviderIdentityMismatchError(), "image_provider_identity_mismatch", "result_unknown"),
        (
            ImageProviderRejectedError(http_status=503, response_kind="json"),
            "image_provider_http_5xx",
            "result_unknown",
        ),
        (ImageProviderRejectedError(http_status=400), "image_provider_rejected", "failed"),
        (ProviderRejectedError(), "image_provider_request_rejected", "result_unknown"),
        (RuntimeError("PRIVATE_SENTINEL provider body"), "image_stage_failed", "result_unknown"),
    ],
)
async def test_exact_text_trial_image_failure_reports_only_bounded_typed_reason(
    tmp_path: Path, failure: Exception, reason: str, state: str
) -> None:
    sentinel = "PRIVATE_SENTINEL https://provider.example/?token=secret"

    class FailingImage(_Models):
        async def generate(self, request: ImageGenerationRequest) -> ImageGenerationResult:
            self.image_requests.append(request)
            raise failure from RuntimeError(sentinel)

    models = FailingImage()
    run_dir = tmp_path / "one-use-run"
    summary = await run_local_batch(
        (_evidence_first_cases()[0],),
        run_dir=run_dir,
        models=models,
        references=_reference(),
        exact_text_quality_trial=True,
        evidence_first_copy_trial=True,
    )
    assert len(models.image_requests) == 1
    assert summary.cases[0]["generation"] == state
    assert summary.cases[0]["reason_code"] == reason
    assert summary.batch_accepted is False
    assert (run_dir / "private" / "01-image.intent.json").is_file()
    assert not list((run_dir / "images").iterdir())
    assert not models.ocr_requests
    assert not models.visual_requests
    assert all(
        b"PRIVATE_SENTINEL" not in path.read_bytes() and sentinel.encode() not in path.read_bytes()
        for path in run_dir.rglob("*")
        if path.is_file()
    )


@pytest.mark.asyncio
async def test_typed_image_reason_is_opt_in_and_invalid_raster_reason_is_unchanged(
    tmp_path: Path,
) -> None:
    case = validate_package_snapshot(package_payload())
    legacy = await run_local_batch(
        (case,),
        run_dir=tmp_path / "legacy",
        models=_Models(fail_image="timeout"),
        references=_reference(),
    )
    assert legacy.cases[0]["reason_code"] == "image_stage_failed"

    exact = await run_local_batch(
        (_evidence_first_cases()[0],),
        run_dir=tmp_path / "exact",
        models=_Models(fail_image="coded_invalid"),
        references=_reference(),
        exact_text_quality_trial=True,
        evidence_first_copy_trial=True,
    )
    assert exact.cases[0]["reason_code"] == "image_dimensions_invalid"
    assert exact.cases[0]["generation"] == "invalid_output"


@pytest.mark.asyncio
async def test_footer_failure_keeps_raw_only_and_never_claims_approval(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import app.application.services.news_infographic as service
    from app.application.services.news_infographic_footer import FooterRenderError

    case = validate_package_snapshot(package_payload())
    monkeypatch.setattr(
        service,
        "render_exact_source_footer",
        lambda *_args: (_ for _ in ()).throw(FooterRenderError("cannot fit")),
    )
    models = _Models()
    summary = await run_local_batch(
        (case,), run_dir=tmp_path / "fresh", models=models, references=_reference()
    )
    outcome = summary.cases[0]
    assert len(models.image_requests) == 1
    assert outcome["generation"] == "generated"
    assert outcome["footer"] == "failed"
    assert outcome["ocr"] == "not_checked_footer_failed"
    assert outcome["visual_audit"] == "not_checked_footer_failed"
    assert "derived_image" not in outcome
    assert (summary.run_dir / str(outcome["image"])).read_bytes() == _png()
    assert not list((summary.run_dir / "images").glob("*-footer.png"))
    assert summary.batch_accepted is False


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("failure", "expected"),
    [
        ("timeout", "result_unknown"),
        ("503", "result_unknown"),
        ("square", "generated_invalid"),
        ("corrupt", "generated_invalid"),
        ("coded_invalid", "invalid_output"),
    ],
)
async def test_first_portrait_gate_stops_batch(tmp_path: Path, failure: str, expected: str) -> None:
    first = validate_package_snapshot(package_payload())
    second = first.model_copy(
        update={
            "package_id": first.copy_generation_run_id,
            "selected_event_version_id": first.selected_event_id,
        }
    )
    models = _Models(fail_image=failure)
    summary = await run_local_batch(
        (first, second), run_dir=tmp_path / "fresh", models=models, references=_reference()
    )
    assert len(models.image_requests) == 1
    assert summary.cases[0]["generation"] == expected
    if failure == "coded_invalid":
        assert summary.cases[0]["reason_code"] == "image_dimensions_invalid"
    assert summary.cases[1]["generation"] == "skipped_after_first_portrait_gate"
    assert summary.batch_accepted is False
    assert (summary.run_dir / "private" / "01-image.intent.json").exists()


@pytest.mark.asyncio
async def test_bad_ocr_never_becomes_passed(tmp_path: Path) -> None:
    case = validate_package_snapshot(package_payload())
    models = _Models(bad_ocr=True)
    summary = await run_local_batch(
        (case,), run_dir=tmp_path / "fresh", models=models, references=_reference()
    )
    assert summary.cases[0]["generation"] == "generated"
    assert summary.cases[0]["ocr"] == "failed"
    assert summary.batch_accepted is False


@pytest.mark.asyncio
async def test_copy_failure_does_not_skip_first_actual_portrait_trial(tmp_path: Path) -> None:
    first = validate_package_snapshot(package_payload())
    second = first.model_copy(
        update={
            "package_id": first.copy_generation_run_id,
            "selected_event_version_id": first.selected_event_id,
        }
    )

    class FirstCopyFails(_Models):
        async def complete_json(self, prompt: str) -> dict[str, object]:
            if not self.prompts:
                self.prompts.append(prompt)
                return {"invalid": "copy"}
            return await super().complete_json(prompt)

    models = FirstCopyFails()
    summary = await run_local_batch(
        (first, second),
        run_dir=tmp_path / "fresh",
        models=models,
        references=_reference(),
    )
    assert summary.cases[0]["copy"] == "failed"
    assert summary.cases[0]["reason_code"] == "copy_stage_failed"
    assert summary.cases[1]["generation"] == "generated"
    assert len(models.image_requests) == 1


@pytest.mark.asyncio
async def test_image_result_identity_mismatch_is_not_accepted(tmp_path: Path) -> None:
    case = validate_package_snapshot(package_payload())

    class WrongImageIdentity(_Models):
        async def generate(self, request: ImageGenerationRequest) -> ImageGenerationResult:
            result = await super().generate(request)
            return ImageGenerationResult(
                provider=result.provider,
                model=result.model,
                request_fingerprint="wrong-request",
                provider_task_id=result.provider_task_id,
                provider_upload_id=result.provider_upload_id,
                image_bytes=result.image_bytes,
                media_type=result.media_type,
                width=result.width,
                height=result.height,
                attempts=result.attempts,
            )

    summary = await run_local_batch(
        (case,),
        run_dir=tmp_path / "wrong-image",
        models=WrongImageIdentity(),
        references=_reference(),
    )
    assert summary.cases[0]["generation"] == "invalid_output"
    assert summary.cases[0]["decode"] == "not_checked"
    assert "image" not in summary.cases[0]


@pytest.mark.asyncio
async def test_visual_audit_wrong_fingerprint_is_not_passed(tmp_path: Path) -> None:
    case = validate_package_snapshot(package_payload())

    class WrongVisualIdentity(_Models):
        async def audit_visual(
            self, request: ImageQualityAuditRequest
        ) -> ImageQualityAuditResult | None:
            return ImageQualityAuditResult(accepted=True, request_fingerprint="wrong-request")

    summary = await run_local_batch(
        (case,),
        run_dir=tmp_path / "wrong-audit",
        models=WrongVisualIdentity(),
        references=_reference(),
    )
    assert summary.cases[0]["visual_audit"] == "invalid_result_identity"
    assert summary.batch_accepted is False


@pytest.mark.asyncio
async def test_disabled_image_judges_do_not_reserve_call_intents(tmp_path: Path) -> None:
    case = validate_package_snapshot(package_payload())

    class DisabledJudges(_Models):
        ocr_enabled = False
        visual_audit_enabled = False

        async def recognize(
            self, request: ImageTextRecognitionRequest
        ) -> ImageTextRecognitionResult | None:
            raise AssertionError("disabled OCR must not be invoked")

        async def audit_visual(
            self, request: ImageQualityAuditRequest
        ) -> ImageQualityAuditResult | None:
            raise AssertionError("disabled visual audit must not be invoked")

    summary = await run_local_batch(
        (case,),
        run_dir=tmp_path / "disabled",
        models=DisabledJudges(),
        references=_reference(),
    )
    assert summary.cases[0]["ocr"] == "unavailable"
    assert summary.cases[0]["visual_audit"] == "unavailable"
    assert not list((summary.run_dir / "private").glob("*ocr.intent.json"))
    assert not list((summary.run_dir / "private").glob("*visual-audit.intent.json"))


@pytest.mark.asyncio
async def test_symlinked_output_parent_is_rejected_before_models(tmp_path: Path) -> None:
    case = validate_package_snapshot(package_payload())
    real_parent = tmp_path / "real"
    real_parent.mkdir()
    linked_parent = tmp_path / "linked"
    linked_parent.symlink_to(real_parent, target_is_directory=True)
    models = _Models()
    with pytest.raises(ValueError, match="symlink"):
        await run_local_batch(
            (case,),
            run_dir=linked_parent / "fresh",
            models=models,
            references=_reference(),
        )
    assert not models.prompts


def test_copy_claim_binding_and_safe_preview() -> None:
    case = validate_package_snapshot(package_payload())
    copy = PosterCopy.model_validate(_copy_payload())
    validate_poster_copy(case, copy)
    prompt = build_image_prompt(case, copy)
    assert case.source_url in prompt
    assert "AI" in prompt
    assert "粮库文字" in prompt
    assert validate_image_generation_request_prompt(
        ImageGenerationRequest(
            run_id=uuid4(),
            draft_version_id=case.draft_version_id,
            prompt=prompt,
            request_fingerprint="sample-poster-preflight",
            unrestricted_prompt_length=True,
        )
    ) == " ".join(prompt.split())
    bad = _copy_payload()
    bad["cards"][2]["claim_ids"] = ["fact-1"]
    with pytest.raises(ValueError, match="brand card"):
        validate_poster_copy(case, PosterCopy.model_validate(bad))
    invented_heading = _copy_payload()
    invented_heading["cards"][2]["heading"] = "在赛先生怎么教"
    with pytest.raises(ValueError, match="brand heading must quote"):
        validate_poster_copy(case, PosterCopy.model_validate(invented_heading))
    with_year = _copy_payload()
    with_year["title"] = "2026年科学课动手探究"
    with pytest.raises(ValueError, match="unsupported number"):
        validate_poster_copy(case, PosterCopy.model_validate(with_year))
    escaped = render_preview(
        (case,),
        [
            {
                "generation": "failed",
                "decode": "not_checked",
                "ocr": "not_checked",
                "visual_audit": "not_checked",
                "human_inspection": "pending",
                "user_approval": "pending",
            }
        ],
        [],
    )
    assert "此条没有生成图片" in escaped


def test_copy_prompt_scopes_each_sections_claim_ids_for_arbitrary_case() -> None:
    payload = deepcopy(package_payload())
    claims = payload["copy"]["claims"]
    claims[0]["claim_id"] = "external-custom"
    claims[1]["claim_id"] = "brand-custom"
    claims.append(
        {
            "claim_id": "opinion-custom",
            "kind": "opinion",
            "text": "孩子可以从身边的问题开始观察。",
            "evidence_ids": [],
            "brand_chunk_ids": [],
        }
    )
    payload["sources"][0]["claim_id"] = "external-custom"
    payload["brand_bindings"][0]["claim_id"] = "brand-custom"
    case = validate_package_snapshot(payload)

    prompt = build_copy_prompt(case)
    context = json.loads(prompt.split("\n", 1)[1])
    assert COPY_VERSION == "daily-news-infographic-copy-v5-fourteen-char-headings"
    assert context["citation_rules"] == {
        "news_summary": {"kinds": ["external_fact"], "claim_ids": ["external-custom"]},
        "science": {"kinds": ["external_fact"], "claim_ids": ["external-custom"]},
        "learning": {
            "kinds": ["external_fact", "opinion"],
            "claim_ids": ["external-custom", "opinion-custom"],
        },
        "brand": {"kinds": ["brand_statement"], "claim_ids": ["brand-custom"]},
    }
    assert "brand卡只能引用brand_statement" in prompt
    assert "不得引用、复述或改写opinion内容" in prompt
    assert "news_claim_ids只能从citation_rules.news_summary.claim_ids选择" in prompt
    assert "各卡的claim_ids只能从citation_rules对应卡的claim_ids选择" in prompt
    assert "不能用常识补足稀疏资料" in prompt
    assert "不能添加定义、原理、因果机制、统计数据、背景事实" in prompt
    assert "science卡也保持宽泛" in prompt
    assert "开放问题或可做的观察活动" in prompt
    assert "不能把opinion预测写成已经发生或被证实的结果" in prompt
    assert "heading从所引用brand_statement文本中选取2-14字的连续短片段并逐字照录" in prompt
    assert "body也只能由所引用brand_statement直接支持" in prompt
    assert "不得增加未绑定的头衔、荣誉、身份" in prompt
    assert context["schema"]["cards"][0]["heading"] == "2-14字，单行宽不超过565像素"
    assert "39像素Noto中文字形时宽度必须不超过565像素" in prompt
    assert "不要靠缩小字号或换行容纳长标题" in prompt

    for length in (13, 14):
        allowed_heading = _copy_payload()
        allowed_heading["cards"][2]["heading"] = "科" * length
        assert len(PosterCopy.model_validate(allowed_heading).cards[2].heading) == length
    too_long_heading = _copy_payload()
    too_long_heading["cards"][2]["heading"] = "科" * 15
    with pytest.raises(ValueError, match="String should have at most 14 characters"):
        PosterCopy.model_validate(too_long_heading)

    copy = PosterCopy.model_validate(_copy_payload())
    audit_prompt = build_copy_audit_prompt(case, copy)
    assert "即使引用了brand_statement，也不得把opinion内容复述或改写成品牌理念" in audit_prompt
    assert "science卡不得把相关常识、定义或推断冒充为所引事实" in audit_prompt
    assert "learning卡不得把opinion中的预测或期望说成已证实结果" in audit_prompt
    assert "brand卡heading是否逐字截取自所引brand_statement的连续片段" in audit_prompt
    assert "标题不得添加无证据的头衔、荣誉、身份、范围或结论" in audit_prompt


@pytest.mark.asyncio
async def test_blocked_poster_prompt_stops_before_image_intent_or_post(tmp_path: Path) -> None:
    case = validate_package_snapshot(package_payload())

    class BlockedCopy(_Models):
        async def complete_json(self, prompt: str) -> dict[str, object]:
            if "逐句检查" in prompt:
                return {"accepted": True, "issues": []}
            copy = _copy_payload()
            copy["news_summary"] = "教育部介绍了科学课中的动手探究方式与二维码示例。"
            return copy

    models = BlockedCopy()
    summary = await run_local_batch(
        (case,), run_dir=tmp_path / "blocked", models=models, references=_reference()
    )
    assert summary.cases[0]["generation"] == "blocked_preflight"
    assert summary.cases[0]["reason_code"] == "image_prompt_rejected"
    assert not models.image_requests
    assert not (summary.run_dir / "private" / "01-image.intent.json").exists()
    assert not (summary.run_dir / "private" / "01-image-request.json").exists()
    assert (summary.run_dir / "private" / "01-copy.intent.json").exists()


@pytest.mark.asyncio
async def test_reused_accepted_copy_skips_chat_and_preserves_provenance(tmp_path: Path) -> None:
    case = validate_package_snapshot(package_payload())

    class NoChatModels(_Models):
        async def complete_json(self, prompt: str) -> dict[str, object]:
            raise AssertionError(f"unexpected chat call: {prompt[:20]}")

    models = NoChatModels()
    summary = await run_local_batch(
        (case,),
        run_dir=tmp_path / "reused",
        models=models,
        references=_reference(),
        accepted_copy=PosterCopy.model_validate(_copy_payload()),
    )
    assert summary.cases[0]["copy"] == "reused_accepted"
    assert summary.cases[0]["copy_provenance"] == "prior_local_accepted_run"
    assert len(models.image_requests) == 1
    assert not (summary.run_dir / "private" / "01-copy.intent.json").exists()
    assert not (summary.run_dir / "private" / "01-copy-audit.intent.json").exists()
    assert not (summary.run_dir / "private" / "01-copy-candidate.json").exists()
    assert not (summary.run_dir / "private" / "01-copy-audit-verdict.json").exists()
    assert (summary.run_dir / "private" / "01-image.intent.json").exists()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("failure", "reason", "copy_state", "has_candidate", "has_audit_intent", "has_verdict"),
    [
        ("copy_schema", "copy_schema_invalid", "failed", False, False, False),
        ("copy_binding", "copy_claim_binding_failed", "failed", True, False, False),
        ("brand_heading", "copy_claim_binding_failed", "failed", True, False, False),
        ("copy_timeout", "copy_provider_timeout", "result_unknown", False, False, False),
        ("copy_rejected", "copy_provider_request_rejected", "failed", False, False, False),
        ("copy_invalid", "copy_provider_invalid_output", "failed", False, False, False),
        ("audit_schema", "copy_audit_schema_invalid", "failed", True, True, False),
        ("audit_rejected", "copy_audit_rejected", "failed", True, True, True),
        ("audit_timeout", "copy_audit_provider_timeout", "result_unknown", True, True, False),
        ("audit_rate_limit", "copy_audit_provider_rate_limited", "failed", True, True, False),
        (
            "audit_unavailable",
            "copy_audit_provider_unavailable",
            "result_unknown",
            True,
            True,
            False,
        ),
        ("audit_unknown", "copy_audit_result_unknown", "result_unknown", True, True, False),
        ("unknown", "copy_model_result_unknown", "result_unknown", False, False, False),
    ],
)
async def test_copy_failure_diagnostics_are_stage_specific_and_private(
    tmp_path: Path,
    failure: str,
    reason: str,
    copy_state: str,
    has_candidate: bool,
    has_audit_intent: bool,
    has_verdict: bool,
) -> None:
    case = validate_package_snapshot(package_payload())

    class FailingModels(_Models):
        async def complete_json(self, prompt: str) -> dict[str, object]:
            self.prompts.append(prompt)
            if "逐句检查" not in prompt:
                if failure == "copy_schema":
                    return {"title": "PRIVATE_SENTINEL", "cards": []}
                if failure == "copy_timeout":
                    raise ProviderTimeoutError()
                if failure == "copy_rejected":
                    raise ProviderRejectedError()
                if failure == "copy_invalid":
                    raise InvalidProviderOutputError(("invalid_schema",))
                if failure == "unknown":
                    raise RuntimeError("PRIVATE_SENTINEL from provider")
                candidate = _copy_payload()
                if failure == "copy_binding":
                    candidate["news_claim_ids"] = ["unknown-claim"]
                if failure == "brand_heading":
                    candidate["cards"][2]["heading"] = "未绑定的品牌标语"
                return candidate
            if failure == "audit_schema":
                return {"accepted": "not-a-boolean", "issues": ["PRIVATE_SENTINEL"]}
            if failure == "audit_rejected":
                return {
                    "accepted": False,
                    "issues": ["unsupported_claim", "PRIVATE_SENTINEL free-form text"],
                }
            if failure == "audit_timeout":
                raise ProviderTimeoutError()
            if failure == "audit_rate_limit":
                raise ProviderRateLimitError()
            if failure == "audit_unavailable":
                raise ProviderUnavailableError()
            if failure == "audit_unknown":
                raise RuntimeError("PRIVATE_SENTINEL from audit provider")
            raise AssertionError("audit should not run")

    models = FailingModels()
    run_dir = tmp_path / failure
    summary = await run_local_batch(
        (case,),
        run_dir=run_dir,
        models=models,
        references=_reference(),
        exact_text_quality_trial=True,
    )
    outcome = summary.cases[0]
    assert outcome["copy"] == copy_state
    assert outcome["reason_code"] == reason
    assert outcome["generation"] == "not_started"
    assert summary.batch_accepted is False
    assert not models.image_requests
    assert not (run_dir / "private" / "01-image.intent.json").exists()
    assert not (run_dir / "private" / "01-image-request.json").exists()
    assert (run_dir / "private" / "01-copy.intent.json").is_file()
    assert (run_dir / "private" / "01-copy-audit.intent.json").exists() is has_audit_intent
    candidate_path = run_dir / "private" / "01-copy-candidate.json"
    verdict_path = run_dir / "private" / "01-copy-audit-verdict.json"
    schema_path = run_dir / "private" / "01-copy-schema-diagnostic.json"
    assert candidate_path.exists() is has_candidate
    assert verdict_path.exists() is has_verdict
    assert schema_path.exists() is (failure == "copy_schema")
    if schema_path.exists():
        assert stat.S_IMODE(schema_path.stat().st_mode) == 0o600
        assert schema_path.stat().st_size < 8 * 1024
        diagnostic = json.loads(schema_path.read_text(encoding="utf-8"))
        assert diagnostic["issues"]
        assert "PRIVATE_SENTINEL" not in schema_path.read_text(encoding="utf-8")
    if has_candidate:
        assert stat.S_IMODE(candidate_path.stat().st_mode) == 0o600
        expected_candidate = _copy_payload()
        if failure == "copy_binding":
            expected_candidate["news_claim_ids"] = ["unknown-claim"]
        if failure == "brand_heading":
            expected_candidate["cards"][2]["heading"] = "未绑定的品牌标语"
        assert json.loads(candidate_path.read_text(encoding="utf-8"))["copy"] == expected_candidate
    if has_verdict:
        assert stat.S_IMODE(verdict_path.stat().st_mode) == 0o600
        private_verdict = json.loads(verdict_path.read_text(encoding="utf-8"))
        assert private_verdict["issue_codes"] == [
            "unsupported_claim",
            "unclassified_issue",
        ]
        assert private_verdict["issues"] == [
            {"text": "unsupported_claim", "truncated": False},
            {"text": "PRIVATE_SENTINEL free-form text", "truncated": False},
        ]
    for public_name in ("quality.json", "manifest.json", "preview.html", "copy.json"):
        assert "PRIVATE_SENTINEL" not in (run_dir / public_name).read_text(encoding="utf-8")
    assert (
        json.loads((run_dir / "manifest.json").read_text(encoding="utf-8"))["send_ready"] is False
    )


@pytest.mark.asyncio
async def test_invalid_nested_heading_keeps_safe_private_schema_shape_and_no_image_intent(
    tmp_path: Path,
) -> None:
    case = validate_package_snapshot(package_payload())
    secret = "PRIVATE_SENTINEL_不可外传"

    class InvalidHeading(_Models):
        async def complete_json(self, prompt: str) -> dict[str, object]:
            assert "逐句检查" not in prompt
            candidate = _copy_payload()
            candidate[secret] = secret
            candidate["cards"][1]["heading"] = secret * 10
            candidate["cards"][1][secret] = secret
            return candidate

    models = InvalidHeading()
    run_dir = tmp_path / "bad-heading"
    summary = await run_local_batch(
        (case,),
        run_dir=run_dir,
        models=models,
        references=_reference(),
        exact_text_quality_trial=True,
    )
    outcome = summary.cases[0]
    assert outcome["copy"] == "failed"
    assert outcome["reason_code"] == "copy_schema_invalid"
    assert outcome["generation"] == "not_started"
    assert not models.image_requests
    assert not (run_dir / "private" / "01-copy-audit.intent.json").exists()
    assert not (run_dir / "private" / "01-image.intent.json").exists()
    assert not (run_dir / "private" / "01-copy-candidate.json").exists()
    private_path = run_dir / "private" / "01-copy-schema-diagnostic.json"
    assert stat.S_IMODE(private_path.stat().st_mode) == 0o600
    diagnostic = json.loads(private_path.read_text(encoding="utf-8"))
    assert {"loc": ["cards", 1, "heading"], "type": "string_too_long"} in diagnostic["issues"]
    assert {"loc": ["cards", 1, "unknown"], "type": "extra_forbidden"} in diagnostic["issues"]
    assert {"loc": ["unknown"], "type": "extra_forbidden"} in diagnostic["issues"]
    assert diagnostic["shape"]["cards"][1]["known_fields"]["heading"] == {
        "type": "string",
        "length": len(secret * 10),
        "length_capped": False,
    }
    assert secret not in private_path.read_text(encoding="utf-8")
    for public_name in ("quality.json", "manifest.json", "preview.html", "copy.json"):
        assert secret not in (run_dir / public_name).read_text(encoding="utf-8")


def test_copy_schema_diagnostic_caps_issue_count_shape_and_unknown_values() -> None:
    from pydantic import ValidationError

    secret = "PRIVATE_SENTINEL_不可外传"
    candidate: dict[str, object] = {
        "title": secret * 100,
        "news_summary": secret * 100,
        "news_claim_ids": [],
        "cards": [{"kind": "invalid", "heading": secret * 100, secret: secret} for _ in range(100)],
        secret: secret,
    }
    error = ValidationError.from_exception_data(
        "PosterCopy",
        [
            {"type": "missing", "loc": ("cards", index, "body"), "input": secret}
            for index in range(30)
        ],
    )
    diagnostic = _private_copy_schema_diagnostic(candidate, error)
    serialized = json.dumps(diagnostic, ensure_ascii=False)
    assert diagnostic["issue_count"] == 12
    assert diagnostic["issues_truncated"] is True
    assert len(diagnostic["issues"]) == 12
    assert len(serialized.encode("utf-8")) < 8 * 1024
    assert secret not in serialized
    assert diagnostic["shape"]["known_fields"]["title"]["length"] == 256
    assert diagnostic["shape"]["known_fields"]["title"]["length_capped"] is True
    assert len(diagnostic["shape"]["cards"]) == 3


@pytest.mark.asyncio
@pytest.mark.parametrize("existing_kind", ["file", "symlink"])
async def test_copy_schema_diagnostic_never_overwrites_existing_target(
    tmp_path: Path, existing_kind: str
) -> None:
    case = validate_package_snapshot(package_payload())
    outside = tmp_path / "outside-target"
    outside.write_text("unchanged", encoding="utf-8")
    run_dir = tmp_path / f"schema-{existing_kind}"

    class BlockedDiagnostic(_Models):
        async def complete_json(self, prompt: str) -> dict[str, object]:
            target = run_dir / "private" / "01-copy-schema-diagnostic.json"
            if existing_kind == "symlink":
                target.symlink_to(outside)
            else:
                target.write_text("unchanged", encoding="utf-8")
            return {"title": "PRIVATE_SENTINEL", "cards": []}

    models = BlockedDiagnostic()
    summary = await run_local_batch(
        (case,),
        run_dir=run_dir,
        models=models,
        references=_reference(),
        exact_text_quality_trial=True,
    )
    assert summary.cases[0]["copy"] == "result_unknown"
    assert summary.cases[0]["reason_code"] == "copy_stage_failed"
    assert outside.read_text(encoding="utf-8") == "unchanged"
    assert (run_dir / "private" / "01-copy-schema-diagnostic.json").read_text(
        encoding="utf-8"
    ) == "unchanged"
    assert not (run_dir / "private" / "01-copy-audit.intent.json").exists()
    assert not (run_dir / "private" / "01-image.intent.json").exists()
    assert not models.image_requests


@pytest.mark.asyncio
async def test_copy_schema_diagnostic_is_opt_in_to_exact_text_trial(tmp_path: Path) -> None:
    case = validate_package_snapshot(package_payload())

    class InvalidCopy(_Models):
        async def complete_json(self, prompt: str) -> dict[str, object]:
            return {"title": "PRIVATE_SENTINEL", "cards": []}

    models = InvalidCopy()
    run_dir = tmp_path / "ordinary-local"
    summary = await run_local_batch(
        (case,), run_dir=run_dir, models=models, references=_reference()
    )
    assert summary.cases[0]["reason_code"] == "copy_stage_failed"
    assert not (run_dir / "private" / "01-copy-schema-diagnostic.json").exists()
    assert not (run_dir / "private" / "01-copy-audit.intent.json").exists()
    assert not (run_dir / "private" / "01-image.intent.json").exists()


@pytest.mark.asyncio
async def test_oversized_candidate_diagnostic_is_bounded_without_image_intent(
    tmp_path: Path,
) -> None:
    case = validate_package_snapshot(package_payload())

    class OversizedCopyModels(_Models):
        async def complete_json(self, prompt: str) -> dict[str, object]:
            assert "逐句检查" not in prompt
            candidate = _copy_payload()
            candidate["news_claim_ids"] = ["PRIVATE_SENTINEL" * 1000]
            return candidate

    models = OversizedCopyModels()
    run_dir = tmp_path / "oversized-candidate"
    summary = await run_local_batch(
        (case,),
        run_dir=run_dir,
        models=models,
        references=_reference(),
        exact_text_quality_trial=True,
    )
    assert summary.cases[0]["reason_code"] == "copy_claim_binding_failed"
    candidate_file = run_dir / "private" / "01-copy-candidate.json"
    assert stat.S_IMODE(candidate_file.stat().st_mode) == 0o600
    assert candidate_file.stat().st_size < 8 * 1024
    snapshot = json.loads(candidate_file.read_text(encoding="utf-8"))
    assert snapshot["copy"] is None
    assert snapshot["copy_omitted"] == "bounded_diagnostic"
    assert len(snapshot["copy_sha256"]) == 64
    assert not models.image_requests
    assert not (run_dir / "private" / "01-image.intent.json").exists()
    assert "PRIVATE_SENTINEL" not in (run_dir / "manifest.json").read_text(encoding="utf-8")


@pytest.mark.asyncio
async def test_rejected_audit_retains_bounded_private_chinese_reason_without_image_intent(
    tmp_path: Path,
) -> None:
    case = validate_package_snapshot(package_payload())
    private_reason = "品牌说法没有对应证据；请核对课程承诺。" * 200

    class RejectedAudit(_Models):
        async def complete_json(self, prompt: str) -> dict[str, object]:
            return (
                {"accepted": False, "issues": [private_reason]}
                if "逐句检查" in prompt
                else _copy_payload()
            )

    models = RejectedAudit()
    run_dir = tmp_path / "rejected-audit"
    summary = await run_local_batch(
        (case,),
        run_dir=run_dir,
        models=models,
        references=_reference(),
        exact_text_quality_trial=True,
    )
    assert summary.cases[0]["reason_code"] == "copy_audit_rejected"
    private_path = run_dir / "private" / "01-copy-audit-verdict.json"
    assert stat.S_IMODE(private_path.stat().st_mode) == 0o600
    assert private_path.stat().st_size < 8 * 1024
    verdict = json.loads(private_path.read_text(encoding="utf-8"))
    assert verdict["issues"][0]["text"].startswith("品牌说法没有对应证据")
    assert len(verdict["issues"][0]["text"].encode("utf-8")) <= 384
    assert verdict["issues"][0]["truncated"] is True
    assert verdict["issue_codes"] == ["unclassified_issue"]
    assert private_reason[:10] not in (run_dir / "manifest.json").read_text(encoding="utf-8")
    assert private_reason[:10] not in (run_dir / "quality.json").read_text(encoding="utf-8")
    assert not models.image_requests
    assert not (run_dir / "private" / "01-image.intent.json").exists()


@pytest.mark.asyncio
@pytest.mark.parametrize("stage", ["candidate", "verdict"])
async def test_private_copy_diagnostic_cannot_overwrite_symlink_target(
    tmp_path: Path, stage: str
) -> None:
    case = validate_package_snapshot(package_payload())
    outside = tmp_path / "outside-private-target"
    outside.write_text("unchanged", encoding="utf-8")
    run_dir = tmp_path / stage

    class SymlinkedDiagnostic(_Models):
        async def complete_json(self, prompt: str) -> dict[str, object]:
            name = (
                "01-copy-audit-verdict.json" if "逐句检查" in prompt else "01-copy-candidate.json"
            )
            if (stage == "candidate" and "逐句检查" not in prompt) or (
                stage == "verdict" and "逐句检查" in prompt
            ):
                (run_dir / "private" / name).symlink_to(outside)
            return {"accepted": True, "issues": []} if "逐句检查" in prompt else _copy_payload()

    models = SymlinkedDiagnostic()
    summary = await run_local_batch(
        (case,),
        run_dir=run_dir,
        models=models,
        references=_reference(),
        exact_text_quality_trial=True,
    )
    assert summary.cases[0]["copy"] == "result_unknown"
    assert summary.cases[0]["reason_code"] == "copy_stage_failed"
    assert outside.read_text(encoding="utf-8") == "unchanged"
    assert not models.image_requests
    assert not (run_dir / "private" / "01-image.intent.json").exists()


@pytest.mark.asyncio
async def test_image_model_is_frozen_in_private_snapshot_and_request_identity(
    tmp_path: Path,
) -> None:
    case = validate_package_snapshot(package_payload())

    class SunburstModels(_Models):
        image_model = "gpt-image-2.5-sunburst"

    class PreviousModels(_Models):
        image_model = "gpt-image-2"

    new_models = SunburstModels()
    previous_models = PreviousModels()
    await run_local_batch(
        (case,), run_dir=tmp_path / "new", models=new_models, references=_reference()
    )
    await run_local_batch(
        (case,), run_dir=tmp_path / "previous", models=previous_models, references=_reference()
    )
    snapshot = json.loads(
        (tmp_path / "new" / "private" / "01-image-request.json").read_text(encoding="utf-8")
    )
    assert snapshot["model"] == "gpt-image-2.5-sunburst"
    assert snapshot["request_fingerprint"] == new_models.image_requests[0].request_fingerprint
    assert (
        new_models.image_requests[0].request_fingerprint
        != previous_models.image_requests[0].request_fingerprint
    )
