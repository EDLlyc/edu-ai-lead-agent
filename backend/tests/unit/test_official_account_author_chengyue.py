"""Composed author follows the frozen identity, never the news photographer credit."""

from __future__ import annotations

import json
import re
from dataclasses import asdict, replace
from html import unescape
from pathlib import Path

import httpx
import pytest
from app.application.ports.official_account_weekly_production import (
    weekly_article_identity_from_snapshot,
)
from app.application.ports.wechat_official_account import (
    WeChatDraftArticleRequest,
    WeChatDraftCreated,
)
from app.application.services.official_account_local import build_generation_prompt
from app.application.services.official_account_strict_prepared import (
    StrictPreparedProjection,
    build_strict_prepared_projection,
    validate_strict_prepared_projection,
)
from app.application.services.wechat_official_account_draft import (
    WeChatOfficialAccountDraftOnlyService,
    WeChatOfficialAccountDraftPreparer,
)
from app.domain.official_account_local import article_package_fingerprint
from app.domain.official_account_visual_pipeline import (
    OBSERVE_VISUAL_PIPELINE_VERSION,
    STRICT_VISUAL_PIPELINE_VERSION,
)
from app.domain.official_account_visual_pipeline import (
    OFFICIAL_ACCOUNT_GENERATED_VISUAL_PROMPT_V4_VERSION as V4,
)
from app.domain.official_account_visual_pipeline import (
    OFFICIAL_ACCOUNT_GENERATED_VISUAL_PROMPT_V5_VERSION as V5,
)
from app.infrastructure.official_account_runtime import official_account_identity_from_settings
from app.infrastructure.wechat_official_account.client import WeChatOfficialAccountApiClient
from pydantic import SecretStr
from test_official_account_body_caption_visibility import _inputs, _with_v5_footer
from test_official_account_strict_prepared import _write, strict_projection  # noqa: F401
from test_official_account_strict_visual_policy import _settings
from test_official_account_strict_visual_worker import _components
from test_official_account_visual_preview import captured  # noqa: F401


@pytest.mark.parametrize(
    "policy", [STRICT_VISUAL_PIPELINE_VERSION, OBSERVE_VISUAL_PIPELINE_VERSION]
)
def test_new_native_author_ignores_stale_setting_but_frozen_v4_keeps_its_author(policy):
    settings = _settings().model_copy(
        update={
            "official_account_local_default_author": "赛先生",
            "official_account_local_visual_pipeline_version": policy,
        }
    )
    current = official_account_identity_from_settings(settings, provider="zhipu", model="glm-5.2")
    assert current.default_author == "程岳" and current.generated_visual_prompt_version == V5
    frozen = replace(current, default_author="赛先生", generated_visual_prompt_version=V4)
    assert weekly_article_identity_from_snapshot(asdict(frozen)) == frozen
    assert weekly_article_identity_from_snapshot(asdict(current)) == current
    legacy = official_account_identity_from_settings(
        settings.model_copy(update={"official_account_local_visual_pipeline_version": None}),
        provider="zhipu",
        model="glm-5.2",
    )
    assert legacy.default_author == "赛先生"
    fixture = official_account_identity_from_settings(settings, provider="fake", model="fixture")
    assert fixture.default_author == "赛先生" and fixture.generated_visual_prompt_version is None


@pytest.mark.asyncio
@pytest.mark.parametrize("wrong_model_author", [False, True])
async def test_actual_worker_prompt_composition_and_wrong_author_gate(wrong_model_author):
    repo, _store, images, image_auditor, executor = _components()
    assert repo.identity.default_author == "程岳"
    original = executor._live_generator.generate
    prompts = []

    async def generate(request):
        prompts.append(build_generation_prompt(request))
        result = await original(request)
        assert result.draft.author == "程岳"
        if wrong_model_author:
            result = replace(result, draft=result.draft.model_copy(update={"author": "赛先生"}))
        return result

    executor._live_generator.generate = generate
    assert await executor.execute_next("author-offline")
    assert len(prompts) == 1 and "<AUTHOR>程岳</AUTHOR>" in prompts[0]
    assert repo.article is not None
    if wrong_model_author:
        assert not repo.article.validation_passed
        assert any(
            issue.code == "article_author_mismatch" and issue.severity == "error"
            for issue in repo.article.validation_issues
        )
        assert repo.draft is None and not images.calls and not image_auditor.calls
    else:
        assert repo.article.validation_passed and repo.article.article.author == "程岳"
        assert repo.draft is not None and len(images.calls) == 5 and len(image_auditor.calls) == 6


@pytest.mark.asyncio
@pytest.mark.parametrize("future", [False, True])
async def test_article_prepared_footer_and_actual_http_payload_keep_exact_composed_author(
    strict_projection: StrictPreparedProjection,  # noqa: F811
    tmp_path: Path,
    future: bool,
) -> None:
    inputs = _inputs(strict_projection)
    original_article = inputs["article"]
    author = (
        official_account_identity_from_settings(
            _settings(), provider="zhipu", model="glm-5.2"
        ).default_author
        if future
        else original_article.author
    )
    assert author == ("程岳" if future else "赛先生")
    article = original_article.model_copy(update={"author": author})
    inputs["article"] = article.model_copy(
        update={"content_fingerprint": article_package_fingerprint(article)}
    )
    if future:
        inputs["evidence"] = tuple(replace(item, prompt_version=V5) for item in inputs["evidence"])
        _with_v5_footer(inputs)
    projection = build_strict_prepared_projection(**inputs)
    validate_strict_prepared_projection(projection.manifest, projection.files)
    if not future:
        assert projection == strict_projection
    assert projection.manifest["author"] == author
    assert projection.manifest["article"]["author"] == author
    assert (
        projection.manifest["media"][:-1] if future else projection.manifest["media"]
    ) == strict_projection.manifest["media"]
    assert inputs["article"].news_context_media == original_article.news_context_media
    prepared = WeChatOfficialAccountDraftPreparer().prepare(_write(projection, tmp_path / "child"))
    assert prepared.author == author
    assert f"我是{author}" in unescape(prepared.body_html)
    images = re.findall(r"<img [^>]+>", prepared.body_html)
    assert (images[:-1] if future else images) == re.findall(
        r"<img [^>]+>", strict_projection.files["article-body.html"].decode()
    )
    credits = [item.credit for item in inputs["media"] if item.role == "context"]
    assert credits and all(credit and credit != "程岳" for credit in credits)
    assert all(credit in unescape(prepared.body_html) for credit in credits)
    typed_requests: list[WeChatDraftArticleRequest] = []
    payloads = []

    class CapturingClient(WeChatOfficialAccountApiClient):
        async def add_draft(self, article: WeChatDraftArticleRequest) -> WeChatDraftCreated:
            typed_requests.append(article)
            return await super().add_draft(article)

    def respond(request: httpx.Request) -> httpx.Response:
        endpoint = request.url.path
        if endpoint == "/cgi-bin/stable_token":
            return httpx.Response(200, json={"access_token": "synthetic-token", "expires_in": 7200})
        if endpoint == "/cgi-bin/media/uploadimg":
            return httpx.Response(200, json={"url": "https://mmbiz.qpic.cn/synthetic.jpg"})
        if endpoint == "/cgi-bin/material/add_material":
            return httpx.Response(200, json={"media_id": "synthetic-thumb"})
        assert endpoint == "/cgi-bin/draft/add"
        payloads.append(json.loads(request.content))
        return httpx.Response(200, json={"media_id": "synthetic-draft"})

    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as transport:
        client = CapturingClient(
            client=transport,
            app_id=SecretStr("synthetic-app"),
            app_secret=SecretStr("synthetic-secret"),
            timeout_seconds=1,
            max_response_bytes=65536,
        )
        receipt = await WeChatOfficialAccountDraftOnlyService(client=client).create_prepared(
            prepared
        )
    assert receipt.not_published
    assert len(typed_requests) == len(payloads) == 1
    assert typed_requests[0].author == author
    outbound = payloads[0]["articles"][0]
    assert outbound["author"] == author and f"我是{author}" in unescape(outbound["content"])
    assert all(credit in unescape(outbound["content"]) for credit in credits)
    if prepared.content_source_url is None:
        assert "content_source_url" not in outbound
    else:
        assert outbound["content_source_url"] == prepared.content_source_url
