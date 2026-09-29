"""Provider-free tests for the forward-only rich advisory producer seam."""

# ruff: noqa: RUF001 -- Chinese text is the poster's exact rendering contract.

from __future__ import annotations

import json
import re
from hashlib import sha256
from io import BytesIO
from uuid import uuid4

import pytest
from app.application.services.news_infographic_advisory import (
    ADVISORY_AUDIT_VERSION,
    ADVISORY_COPY_VERSION,
    ADVISORY_GENERATION_PROMPT_VERSION,
    ADVISORY_IMAGE_PROMPT_VERSION,
    ADVISORY_NOTICE,
    ADVISORY_POLICY_VERSION,
    AdvisoryCopyError,
    build_advisory_audit_prompt,
    build_advisory_generation_prompt,
    build_advisory_image_prompt,
    build_advisory_rich_copy,
    render_advisory_notice,
)
from app.application.services.news_infographic_footer import render_exact_source_footer
from app.application.services.news_infographic_rich_copy import (
    build_moments_rich_draft_plan,
    build_moments_rich_seed,
)
from app.application.services.wecom_news_infographic import prepare_infographic_group_jpeg
from PIL import Image, ImageChops
from test_news_infographic_rich_copy import (
    _binding,
    _fake_moments_flat_draft,
    _frozen_real_cases,
)


def _frozen():  # type: ignore[no-untyped-def]
    case = _frozen_real_cases()[0]
    binding = _binding(case)
    draft = _fake_moments_flat_draft(case, binding, build_moments_rich_seed(case, binding))
    return case, binding, draft.model_dump()


def test_same_package_rich_copy_pins_exact_fact_brand_and_model_painted_cards() -> None:
    case, binding, fields = _frozen()
    generation_prompt = build_advisory_generation_prompt(case, binding)
    assert case.topic_title in generation_prompt
    assert "不需要因担心审核不通过而返回空对象" in generation_prompt
    assert case.source_url not in generation_prompt
    assert ADVISORY_POLICY_VERSION == "wecom-news-infographic-v13-boundary-comma-advisory"
    assert ADVISORY_COPY_VERSION == "wecom-infographic-advisory-concise-copy-v6"
    assert ADVISORY_GENERATION_PROMPT_VERSION == "wecom-infographic-advisory-concise-generation-v6"
    assert ADVISORY_AUDIT_VERSION == "wecom-infographic-advisory-copy-audit-v4"
    assert ADVISORY_IMAGE_PROMPT_VERSION == "wecom-infographic-advisory-concise-painted-image-v5"
    assert generation_prompt.startswith(ADVISORY_GENERATION_PROMPT_VERSION)
    assert '"final_visible_max_chars"' in generation_prompt
    copy = build_advisory_rich_copy(case, binding, fields)
    assert copy.policy_version == ADVISORY_COPY_VERSION
    assert copy.package_id == case.package_id
    assert copy.source_url == case.source_url
    assert copy.exact_fact in copy.news_body
    assert copy.exact_brand in copy.brand_body
    assert copy.normalized_exact_prefixes == ()
    assert copy.normalized_boundary_commas == ()
    assert copy.brand_body == copy.exact_brand + "。" + fields["brand"]
    assert len(copy.top_summary) <= 58
    assert len(copy.news_body) <= 96
    assert len(copy.child_body) <= 90
    assert len(copy.brand_body) <= 108
    assert copy.warning_codes == ()
    assert copy.content_approved is False
    prompt = build_advisory_image_prompt(case, copy)
    assert prompt.startswith(ADVISORY_IMAGE_PROMPT_VERSION)
    assert "各卡正文最多四行" in prompt
    assert all(
        paragraph in prompt
        for paragraph in (copy.top_summary, copy.news_body, copy.child_body, copy.brand_body)
    )
    assert copy.source_url not in prompt
    assert "y1858–2048" in prompt
    assert "顶部 y0–100" in prompt


def test_numeric_paraphrase_is_warning_not_fake_content_pass() -> None:
    case, binding, fields = _frozen()
    fields["news"] = "解读：可以核对100小时这个说法。"
    copy = build_advisory_rich_copy(case, binding, fields)
    assert {"copy_binding_warning", "copy_layout_warning"} & set(copy.warning_codes)
    assert "100小时" in copy.news_body
    assert copy.content_approved is False
    audit_prompt = build_advisory_audit_prompt(case, binding, copy)
    assert "100小时" in audit_prompt
    assert copy.exact_fact in audit_prompt
    assert "不能确认时给出负面标记" in audit_prompt


def test_concise_budget_rejects_old_long_draft_and_repeated_fixed_text() -> None:
    case, binding, fields = _frozen()
    seed = build_moments_rich_seed(case, binding)
    plan = build_moments_rich_draft_plan(case, binding, seed)
    long = {name: value * 4 for name, value in fields.items()}
    with pytest.raises(AdvisoryCopyError):
        build_advisory_rich_copy(case, binding, long)
    repeated = dict(fields)
    repeated["top"] = plan.fact.text
    with pytest.raises(AdvisoryCopyError, match="repeats"):
        build_advisory_rich_copy(case, binding, repeated)

    # The inserted sentence boundary belongs to the *visible* purple-card budget.
    over_budget_with_period = dict(fields)
    over_budget_with_period["brand"] = "引导孩子先观察再提问。" + "教" * (
        108 - len(plan.brand.text) - len("引导孩子先观察再提问。")
    )
    with pytest.raises(AdvisoryCopyError, match="visible-text budget"):
        build_advisory_rich_copy(case, binding, over_budget_with_period)
    repeated = dict(fields)
    repeated["child"] = plan.child_frame + plan.child_frame + fields["child"]
    with pytest.raises(AdvisoryCopyError, match="outside its prefix"):
        build_advisory_rich_copy(case, binding, repeated)
    repeated = dict(fields)
    repeated["top"] = fields["news"]
    with pytest.raises(AdvisoryCopyError, match="repeats"):
        build_advisory_rich_copy(case, binding, repeated)


def test_one_exact_prefix_is_removed_once_with_raw_provenance_and_combined_budgets() -> None:
    case, binding, fields = _frozen()
    plan = build_moments_rich_draft_plan(case, binding, build_moments_rich_seed(case, binding))
    raw = dict(fields)
    raw["news"] = plan.fact.text + fields["news"]
    raw["child"] = plan.child_frame + fields["child"]
    raw["brand"] = plan.brand.text + "。" + fields["brand"]
    frozen_raw = dict(raw)
    copy = build_advisory_rich_copy(case, binding, raw)
    assert raw == frozen_raw  # Parsing/normalization never mutates the provider response.
    assert copy.normalized_exact_prefixes == ("news", "child", "brand")
    assert copy.normalized_boundary_commas == ()
    assert (
        copy.raw_draft_sha256
        == sha256(
            json.dumps(raw, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
    )
    assert copy.news_body == plan.fact.text + fields["news"]
    assert copy.child_body == plan.child_frame + fields["child"]
    assert copy.brand_body == plan.brand.text + "。" + fields["brand"]
    assert len(copy.news_body) <= 96
    assert len(copy.child_body) <= 90
    assert len(copy.brand_body) <= 108
    assert build_advisory_audit_prompt(case, binding, copy)
    assert build_advisory_image_prompt(case, copy)


@pytest.mark.parametrize("role", ["news", "child", "brand"])
@pytest.mark.parametrize("comma", ["，", ","])
def test_one_leading_boundary_comma_is_removed_from_only_its_continuation(
    role: str, comma: str
) -> None:
    case, binding, fields = _frozen()
    baseline = build_advisory_rich_copy(case, binding, fields)
    raw = dict(fields)
    raw[role] = comma + fields[role]
    copy = build_advisory_rich_copy(case, binding, raw)
    assert raw[role] == comma + fields[role]
    assert (
        copy.raw_draft_sha256
        == sha256(
            json.dumps(raw, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
    )
    assert copy.normalized_exact_prefixes == ()
    assert copy.normalized_boundary_commas == (role,)
    assert (copy.news_body, copy.child_body, copy.brand_body) == (
        baseline.news_body,
        baseline.child_body,
        baseline.brand_body,
    )
    assert build_advisory_audit_prompt(case, binding, copy)
    assert build_advisory_image_prompt(case, copy)


def test_boundary_comma_after_exact_prefix_is_recorded_separately() -> None:
    case, binding, fields = _frozen()
    plan = build_moments_rich_draft_plan(case, binding, build_moments_rich_seed(case, binding))
    raw = dict(fields)
    raw["brand"] = plan.brand.text + "。" + "，" + fields["brand"]
    copy = build_advisory_rich_copy(case, binding, raw)
    assert copy.normalized_exact_prefixes == ("brand",)
    assert copy.normalized_boundary_commas == ("brand",)
    assert copy.brand_body == plan.brand.text + "。" + fields["brand"]


@pytest.mark.parametrize("leading", ["，，", ",,", "，。", "， ", ",\t"])
def test_multiple_punctuation_or_whitespace_after_one_comma_still_fails(leading: str) -> None:
    case, binding, fields = _frozen()
    fields["brand"] = leading + fields["brand"]
    with pytest.raises(AdvisoryCopyError, match=r"invalid sentence boundary|control characters"):
        build_advisory_rich_copy(case, binding, fields)


def test_boundary_comma_does_not_relax_top_empty_budget_or_binding_gates() -> None:
    case, binding, fields = _frozen()
    fields["top"] = "，" + fields["top"]
    with pytest.raises(AdvisoryCopyError, match="invalid sentence boundary"):
        build_advisory_rich_copy(case, binding, fields)
    fields = _frozen()[2]
    fields["brand"] = "，"
    with pytest.raises(AdvisoryCopyError, match="visible-text budget"):
        build_advisory_rich_copy(case, binding, fields)
    fields["brand"] = "，" + fields["brand"] + "教学" * 80
    with pytest.raises(AdvisoryCopyError, match="visible-text budget"):
        build_advisory_rich_copy(case, binding, fields)
    plan = build_moments_rich_draft_plan(case, binding, build_moments_rich_seed(case, binding))
    fields["brand"] = "，" + plan.brand.text
    with pytest.raises(AdvisoryCopyError, match="repeats"):
        build_advisory_rich_copy(case, binding, fields)
    fields["brand"] = "，新闻来源：https://example.org/other"
    with pytest.raises(AdvisoryCopyError, match="source attribution"):
        build_advisory_rich_copy(case, binding, fields)


def test_nonprefix_and_broken_fixed_prefix_are_not_fuzzy_rewritten() -> None:
    case, binding, fields = _frozen()
    plan = build_moments_rich_draft_plan(case, binding, build_moments_rich_seed(case, binding))
    nonprefix = dict(fields)
    nonprefix["child"] = "先看看新闻。" + plan.child_frame + "再提一个问题。"
    with pytest.raises(AdvisoryCopyError, match="outside its prefix"):
        build_advisory_rich_copy(case, binding, nonprefix)
    broken = dict(fields)
    broken["child"] = plan.child_frame[:10] + "错" + fields["child"]
    with pytest.raises(AdvisoryCopyError, match="broken frozen prefix"):
        build_advisory_rich_copy(case, binding, broken)
    truncated = dict(fields)
    truncated["child"] = plan.child_frame
    with pytest.raises(AdvisoryCopyError, match="visible-text budget"):
        build_advisory_rich_copy(case, binding, truncated)
    topical = dict(fields)
    topical["brand"] = "用思维链教学法也可以请孩子先猜想，再对照新闻原句。"
    assert build_advisory_rich_copy(case, binding, topical).normalized_exact_prefixes == ()
    nearly_copied = dict(fields)
    nearly_copied["brand"] = plan.brand.text[:-2] + "另一种说法，仍值得核对。"
    with pytest.raises(AdvisoryCopyError, match="broken frozen prefix"):
        build_advisory_rich_copy(case, binding, nearly_copied)


def test_top_cannot_repeat_the_blue_cards_bound_numeric_fact() -> None:
    case, binding, fields = _frozen()
    plan = build_moments_rich_draft_plan(case, binding, build_moments_rich_seed(case, binding))
    number = re.findall(r"\d+(?:[.,]\d+)*", plan.fact.text)[0]
    fields["top"] = f"围绕{number}这个数字，先和孩子聊聊为什么值得进一步追问。"
    with pytest.raises(AdvisoryCopyError, match="top repeats a frozen numeric fact"):
        build_advisory_rich_copy(case, binding, fields)


def test_concise_copy_does_not_silently_truncate_and_tampered_image_copy_fails() -> None:
    case, binding, fields = _frozen()
    copy = build_advisory_rich_copy(case, binding, fields)
    assert copy.news_body == copy.exact_fact + fields["news"]
    assert copy.child_body.endswith(fields["child"])
    assert copy.brand_body == copy.exact_brand + "。" + fields["brand"]
    with pytest.raises(AdvisoryCopyError, match="frozen source"):
        build_advisory_image_prompt(
            case, copy.model_copy(update={"brand_body": copy.brand_body + "很长的重复说明。" * 20})
        )
    with pytest.raises(AdvisoryCopyError, match="frozen source"):
        build_advisory_image_prompt(
            case,
            copy.model_copy(
                update={"exact_fact": "伪造事实", "news_body": "伪造事实" + fields["news"]}
            ),
        )
    with pytest.raises(AdvisoryCopyError, match="frozen source"):
        build_advisory_image_prompt(
            case, copy.model_copy(update={"brand_body": copy.exact_brand + fields["brand"]})
        )
    with pytest.raises(AdvisoryCopyError, match="exceeds concise layout"):
        build_advisory_image_prompt(
            case, copy.model_copy(update={"brand_heading": "教学启发：" + "科" * 40})
        )
    with pytest.raises(AdvisoryCopyError, match="exceeds concise layout"):
        build_advisory_image_prompt(case, copy.model_copy(update={"title": "新闻" * 40}))
    fields["brand"] += "……"
    with pytest.raises(AdvisoryCopyError, match="ellipsis"):
        build_advisory_rich_copy(case, binding, fields)
    fields["brand"] = "。先观察，再提问并记录想法。"
    with pytest.raises(AdvisoryCopyError, match="invalid sentence boundary"):
        build_advisory_rich_copy(case, binding, fields)


def test_too_thin_or_missing_field_and_wrong_binding_are_hard() -> None:
    case, binding, fields = _frozen()
    fields["child"] = "问孩子。"
    with pytest.raises(AdvisoryCopyError, match="visible-text budget"):
        build_advisory_rich_copy(case, binding, fields)
    fields = _frozen()[2]
    copy = build_advisory_rich_copy(case, binding, fields)
    with pytest.raises(AdvisoryCopyError, match="unavailable"):
        build_advisory_rich_copy(case, binding, {"news": "缺少三个字段"})
    with pytest.raises(AdvisoryCopyError, match="unavailable"):
        build_advisory_rich_copy(
            case, binding.model_copy(update={"active_draft_version_id": uuid4()}), fields
        )
    with pytest.raises(AdvisoryCopyError, match="frozen source"):
        build_advisory_image_prompt(
            case, copy.model_copy(update={"source_url": "https://example.org/other"})
        )
    fields["brand"] = "新闻来源：https://example.org/other"
    with pytest.raises(AdvisoryCopyError, match="source attribution"):
        build_advisory_rich_copy(case, binding, fields)


def test_warning_is_drawn_into_pixels_without_changing_cards_or_footer() -> None:
    source = Image.new("RGB", (1152, 2048), "#a8d5ef")
    raw = BytesIO()
    source.save(raw, format="PNG")
    marked = render_advisory_notice(raw.getvalue())
    with Image.open(BytesIO(marked)) as opened:
        opened.load()
        assert opened.size == (1152, 2048)
        assert opened.getpixel((5, 5)) == (135, 35, 35)
        assert (
            ImageChops.difference(
                opened.crop((0, 100, 1152, 2048)), source.crop((0, 100, 1152, 2048))
            ).getbbox()
            is None
        )
        assert len(ADVISORY_NOTICE) > 0
    with pytest.raises(AdvisoryCopyError, match="geometry"):
        tiny = BytesIO()
        Image.new("RGB", (10, 10)).save(tiny, format="PNG")
        render_advisory_notice(tiny.getvalue())


def test_final_source_footer_and_notice_survive_exact_group_jpeg() -> None:
    case, _, _ = _frozen()
    source = BytesIO()
    Image.new("RGB", (1152, 2048), "#a8d5ef").save(source, format="PNG")
    marked = render_advisory_notice(source.getvalue())
    footer = render_exact_source_footer(marked, case, mode="formal")
    jpeg = prepare_infographic_group_jpeg(footer.image_bytes, max_bytes=2 * 1024 * 1024)
    assert footer.source_url_lines == ()
    with Image.open(BytesIO(jpeg)) as opened:
        opened.load()
        assert opened.format == "JPEG" and opened.size == (1152, 2048)
        red = opened.getpixel((5, 5))
        assert red[0] > red[1] * 2 and red[0] > red[2] * 2


def test_formal_raster_is_unmarked_and_pixel_identical() -> None:
    from app.application.services.news_infographic_advisory import (
        prepare_unmarked_advisory_raster,
    )
    from app.application.services.wecom_infographic_quality import ADVISORY_NOTICE_VERSION

    source = Image.new("RGB", (1152, 2048), "#a8d5ef")
    raw = BytesIO()
    source.save(raw, format="PNG")
    unmarked = prepare_unmarked_advisory_raster(raw.getvalue())
    with Image.open(BytesIO(unmarked)) as opened:
        opened.load()
        assert opened.size == (1152, 2048)
        assert ImageChops.difference(opened.convert("RGB"), source).getbbox() is None
    assert ADVISORY_NOTICE_VERSION.endswith("-unmarked")
    with pytest.raises(AdvisoryCopyError, match="geometry"):
        tiny = BytesIO()
        Image.new("RGB", (10, 10)).save(tiny, format="PNG")
        prepare_unmarked_advisory_raster(tiny.getvalue())
