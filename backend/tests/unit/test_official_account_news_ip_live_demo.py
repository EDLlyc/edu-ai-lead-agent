from __future__ import annotations

# ruff: noqa: RUF001 -- Chinese source fixtures are intentional.
import json
from dataclasses import replace
from hashlib import sha256
from io import BytesIO
from pathlib import Path
from uuid import uuid4

import app.official_account_news_ip_live_demo as news_demo
import pytest
from app.application.ports.official_account_local import OfficialAccountSourceMedia
from app.application.services.official_account_visual_generation import (
    build_generated_visual_prompt,
    plan_generated_body_visual,
)
from app.core.config import Settings
from app.core.errors import ImageProviderTimeoutError
from app.domain.official_account_local import (
    OFFICIAL_ACCOUNT_GENERATED_VISUAL_PLAN_V2_VERSION,
    OFFICIAL_ACCOUNT_GENERATED_VISUAL_PLAN_VERSION,
    OFFICIAL_ACCOUNT_GENERATED_VISUAL_PROMPT_V2_VERSION,
    OFFICIAL_ACCOUNT_GENERATED_VISUAL_PROMPT_VERSION,
)
from app.official_account_news_ip_live_demo import (
    NEWS_FETCH_URL,
    NEWS_URL,
    PAID_CALL_LIMIT,
    PLAN_URL,
    EvidenceSnapshot,
    _article,
    _parse_source,
    _preflight,
    _render,
    _write_intent,
    run,
)
from PIL import Image
from pydantic import SecretStr


def _source_html(*, title: str, published: str, text: str) -> bytes:
    return (
        '<!doctype html><html><head><meta name="ArticleTitle" '
        f'content="{title}"><meta name="publishdate" content="{published}"></head>'
        f"<body><main>{text}</main></body></html>"
    ).encode()


def _evidence() -> tuple[EvidenceSnapshot, EvidenceSnapshot]:
    news = _parse_source(
        _source_html(
            title="面向未来，向新而行",
            published="2026-07-21",
            text=(
                "基础教育必须从传统的知识传授转向更加注重创新能力和综合素养培育。"
                "科技教育以更加鲜明的学科融合和实践导向持续发力。"
            ),
        ),
        canonical_url=NEWS_URL,
        retrieval_url=NEWS_FETCH_URL,
        expected_title="面向未来，向新而行",
        expected_date="2026-07-21",
        required_fact="创新能力和综合素养培育",
        quote="科技教育以更加鲜明的学科融合和实践导向持续发力",
    )
    plan = _parse_source(
        _source_html(
            title="教育部等五部门关于印发《“人工智能+教育”行动计划》的通知",
            published="2026-04-10",
            text="坚持育人为本、素养为先、应用导向、智能向善。鼓励开展人工智能跨学科教学。",
        ),
        canonical_url=PLAN_URL,
        retrieval_url=PLAN_URL,
        expected_title="教育部等五部门关于印发《“人工智能+教育”行动计划》的通知",
        expected_date="2026-04-10",
        required_fact="坚持育人为本、素养为先、应用导向、智能向善",
        quote="鼓励开展人工智能跨学科教学",
    )
    return news, plan


def _reference_jpeg() -> bytes:
    output = BytesIO()
    Image.new("RGB", (900, 600), (32, 78, 96)).save(
        output,
        format="JPEG",
        quality=82,
        exif=b"",
    )
    return output.getvalue()


def _reference() -> OfficialAccountSourceMedia:
    body = _reference_jpeg()
    return OfficialAccountSourceMedia(
        source_image_artifact_id=None,
        fixture_id="catalog:33586a916bbbfbf1",
        media_type="image/jpeg",
        byte_size=len(body),
        sha256=sha256(body).hexdigest(),
        candidate_id="33586a916bbbfbf1",
        catalog_asset_ref="33586a916bbbfbf1",
        catalog_version="brand-visual-catalog-v1",
        source_master_sha256="a" * 64,
        assigned_section_index=0,
        selection_method="deterministic_tag",
        similarity_band=None,
    )


def test_news_article_binds_external_facts_to_exact_official_sources() -> None:
    article = _article(_evidence())

    assert tuple(source.source_url for source in article.article.sources) == (NEWS_URL, PLAN_URL)
    evidence_ids = {source.evidence_id for source in article.article.sources}
    external = tuple(claim for claim in article.article.claims if claim.kind == "external_fact")
    opinion = tuple(claim for claim in article.article.claims if claim.kind == "opinion")
    assert external and all(set(claim.evidence_ids) <= evidence_ids for claim in external)
    assert opinion and all(
        not claim.evidence_ids and not claim.brand_chunk_ids for claim in opinion
    )
    assert _render(article).canonical_html.count("__OFFICIAL_ACCOUNT_BODY_MEDIA_") == 3


def test_source_snapshot_is_bounded_and_fails_if_required_fact_changes() -> None:
    news, _plan = _evidence()
    assert news.canonical_url == NEWS_URL
    assert news.retrieval_url == NEWS_FETCH_URL
    assert len(news.exact_quote) < 80
    assert len(news.document_sha256) == 64

    with pytest.raises(ValueError, match="required fact changed"):
        _parse_source(
            _source_html(title="面向未来，向新而行", published="2026-07-21", text="漂移"),
            canonical_url=NEWS_URL,
            retrieval_url=NEWS_FETCH_URL,
            expected_title="面向未来，向新而行",
            expected_date="2026-07-21",
            required_fact="创新能力和综合素养培育",
            quote="科技教育以更加鲜明的学科融合和实践导向持续发力",
        )


def test_v3_prompt_requires_visible_ip_and_v2_remains_frozen() -> None:
    article = _article(_evidence())
    reference = _reference()
    render = _render(article)
    current = build_generated_visual_prompt(
        article=article,
        section_index=0,
        reference=reference,
        prompt_version=OFFICIAL_ACCOUNT_GENERATED_VISUAL_PROMPT_VERSION,
    )
    historical = build_generated_visual_prompt(
        article=article,
        section_index=0,
        reference=reference,
        prompt_version=OFFICIAL_ACCOUNT_GENERATED_VISUAL_PROMPT_V2_VERSION,
    )

    assert "same Xiaosai / Sai Xiansheng character as the clear protagonist" in current
    assert "must be fully visible and visually unmistakable" in current
    assert "may guide character identity" in historical
    assert "must be fully visible" not in historical
    assert current != historical
    current_plan = plan_generated_body_visual(
        run_id=uuid4(),
        article=article,
        render=render,
        ordinal=0,
        reference=reference,
        provider="toapis",
        model="gpt-image-2",
        reference_bytes=_reference_jpeg(),
    )
    old_plan = plan_generated_body_visual(
        run_id=current_plan.run_id,
        article=article,
        render=render,
        ordinal=0,
        reference=reference,
        provider="toapis",
        model="gpt-image-2",
        reference_bytes=_reference_jpeg(),
        plan_version=OFFICIAL_ACCOUNT_GENERATED_VISUAL_PLAN_V2_VERSION,
        prompt_version=OFFICIAL_ACCOUNT_GENERATED_VISUAL_PROMPT_V2_VERSION,
    )
    assert current_plan.plan_version == OFFICIAL_ACCOUNT_GENERATED_VISUAL_PLAN_VERSION
    assert current_plan.request_fingerprint != old_plan.request_fingerprint


def test_news_demo_preflight_forces_toapis_single_attempt_without_comfly(tmp_path: Path) -> None:
    settings = Settings(
        _env_file=None,
        image_provider_mode="comfly",
        comfly_base_url="https://comfly.test",
        comfly_api_key=SecretStr("unused-compromised-key"),
        toapis_base_url="https://toapis.com",
        toapis_api_key=SecretStr("test-only-toapis-key"),
        image_max_attempts=3,
    )

    live = _preflight(settings, tmp_path / "fresh")
    assert live.image_provider_mode == "toapis"
    assert live.image_max_attempts == 1
    assert settings.image_provider_mode == "comfly"


def test_paid_call_intent_is_durable_exclusive_and_contains_no_prompt(tmp_path: Path) -> None:
    article = _article(_evidence())
    reference = _reference()
    plan = plan_generated_body_visual(
        run_id=uuid4(),
        article=article,
        render=_render(article),
        ordinal=0,
        reference=reference,
        provider="toapis",
        model="gpt-image-2",
        reference_bytes=_reference_jpeg(),
    )
    output = tmp_path / "run"
    output.mkdir()

    _write_intent(output, ordinal=0, plan=plan)
    payload = json.loads((output / "intents/body-0.intent.json").read_text())
    assert PAID_CALL_LIMIT == 3
    assert payload["automatic_retry_permitted"] is False
    assert payload["paid_call_limit"] == 3
    assert "prompt_text" not in payload
    assert "scene_brief" not in payload
    with pytest.raises(FileExistsError):
        _write_intent(output, ordinal=0, plan=replace(plan))


@pytest.mark.asyncio
async def test_timeout_marks_exact_intent_unknown_and_stops_without_a_second_call(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = 0
    reference = _reference()

    async def load_local_evidence(**_kwargs: object):
        return (*_evidence(), 0)

    async def load_local_references(_settings: Settings):
        return tuple(
            (replace(reference, ordinal=ordinal, assigned_section_index=ordinal), _reference_jpeg())
            for ordinal in range(PAID_CALL_LIMIT)
        )

    class TimeoutGenerator:
        async def generate(self, _request: object):
            nonlocal calls
            calls += 1
            raise ImageProviderTimeoutError()

    settings = Settings(
        _env_file=None,
        toapis_base_url="https://toapis.com",
        toapis_api_key=SecretStr("test-only-toapis-key"),
    )
    monkeypatch.setattr(news_demo, "get_settings", lambda: settings)
    monkeypatch.setattr(news_demo, "load_evidence", load_local_evidence)
    monkeypatch.setattr(news_demo, "_references", load_local_references)
    monkeypatch.setattr(
        news_demo,
        "create_image_generator",
        lambda _settings, *, client: TimeoutGenerator(),
    )

    output = tmp_path / "timeout-run"
    assert await run(output) is False
    assert calls == 1
    result = json.loads((output / "intents/body-0.result.json").read_text())
    run_result = json.loads((output / "run.json").read_text())
    assert result["state"] == "result_unknown"
    assert result["safe_error_code"] == "image_provider_timeout"
    assert result["automatic_retry_permitted"] is False
    assert run_result["paid_generation_calls_attempted"] == 1
    assert run_result["paid_generation_calls_succeeded"] == 0
    assert not (output / "intents/body-1.intent.json").exists()
