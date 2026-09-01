# ruff: noqa: RUF001 -- Full-width Chinese punctuation is intentional fixture copy.

from __future__ import annotations

import json
from io import BytesIO
from pathlib import Path

import httpx
import pytest
from app.application.services.official_account_editor_handoff_v2 import EditorHandoffV2Artifact
from app.core.config import Settings
from app.core.errors import PermanentFetchError
from app.domain.official_account_editor_handoff_v2 import EditorHandoffMobileValidation
from app.infrastructure.ingestion.fetcher import SafeHttpFetcher
from app.infrastructure.ingestion.source_image_fetcher import SafeSourceImageFetcher
from app.official_account_weekly_edition_demo import fixture_mobile_validation
from app.official_account_weekly_edition_live_demo import (
    _source_excerpts,
    acquire_live_weekly_news,
    build_live_weekly_edition_artifact,
    load_live_weekly_input,
)
from PIL import Image

_ROOT = Path(__file__).resolve().parents[3]
_INPUT = _ROOT / "docs/portfolio/fixtures/official-account-weekly-live-input-2026-08-31.json"
_THEME_INPUT = (
    _ROOT / "docs/portfolio/fixtures/official-account-weekly-live-theme-clusters-2026-08-31.json"
)


async def _public_resolver(_host: str) -> list[str]:
    return ["93.184.216.34"]


def _image_bytes(media_type: str, color: tuple[int, int, int]) -> bytes:
    output = BytesIO()
    Image.new("RGB", (640, 360), color).save(
        output,
        format={"image/jpeg": "JPEG", "image/png": "PNG"}[media_type],
    )
    return output.getvalue()


def _page(
    title: str,
    published: str,
    image_url: str,
    *,
    selector: str,
    lead_sentence: str = "",
) -> bytes:
    body = "".join(
        f"<p>{published}，{title}的来源页独立事实段落 {ordinal}。"
        "本段用于验证真实来源、日期、证据和新闻图片在三个子文章之间不会交叉复用。"
        "读者仍须回到原始页面核对完整上下文。</p>"
        for ordinal in range(8)
    )
    return (
        "<!doctype html><html><head>"
        f'<meta property="og:title" content="{title}">'
        f'<meta property="article:published_time" content="{published}T12:00:00+08:00">'
        "</head><body>"
        f'<div class="{selector.removeprefix(".")}" id="{selector.removeprefix("#")}">'
        f"<p>{lead_sentence}</p>{body}"
        f'<img src="{image_url}" width="640" height="360" alt="{title}现场原图">'
        "</div></body></html>"
    ).encode()


@pytest.mark.asyncio
async def test_live_weekly_mock_transport_builds_three_distinct_news_children() -> None:
    live_input = load_live_weekly_input(_INPUT)
    image_payloads = {
        live_input.articles[0].preferred_image_urls[0]: (
            "image/jpeg",
            _image_bytes("image/jpeg", (20, 86, 122)),
        ),
        live_input.articles[1].preferred_image_urls[0]: (
            "image/jpeg",
            _image_bytes("image/jpeg", (43, 92, 170)),
        ),
        live_input.articles[2].preferred_image_urls[0]: (
            "image/png",
            _image_bytes("image/png", (25, 135, 113)),
        ),
    }
    page_payloads = {
        live_input.articles[0].url: _page(
            live_input.articles[0].expected_title,
            live_input.articles[0].expected_published_date.isoformat(),
            live_input.articles[0].preferred_image_urls[0],
            selector=".TRS_UEDITOR",
        ),
        live_input.articles[1].url: _page(
            live_input.articles[1].expected_title,
            live_input.articles[1].expected_published_date.isoformat(),
            live_input.articles[1].preferred_image_urls[0],
            selector="#detail",
        ),
        live_input.articles[2].url: _page(
            live_input.articles[2].expected_title,
            live_input.articles[2].expected_published_date.isoformat(),
            live_input.articles[2].preferred_image_urls[0],
            selector="#detail",
            lead_sentence="南京人工智能智能终端消费中心展示多种可体验的应用场景。",
        ),
    }
    requests: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        requests.append(url)
        if url in page_payloads:
            return httpx.Response(
                200,
                headers={"Content-Type": "text/html; charset=utf-8"},
                content=page_payloads[url],
            )
        media_type, body = image_payloads[url]
        return httpx.Response(200, headers={"Content-Type": media_type}, content=body)

    transport = httpx.MockTransport(handler)
    validated_children: list[str] = []

    def validate_mobile(artifact: EditorHandoffV2Artifact) -> EditorHandoffMobileValidation:
        validated_children.append(artifact.content_fingerprint)
        return fixture_mobile_validation(artifact)

    artifact = await build_live_weekly_edition_artifact(
        live_input,
        page_fetcher=SafeHttpFetcher(
            Settings(),
            resolver=_public_resolver,
            transport=transport,
        ),
        image_fetcher=SafeSourceImageFetcher(
            Settings(),
            resolver=_public_resolver,
            transport=transport,
        ),
        mobile_validation_factory=validate_mobile,
    )

    assert requests == [
        live_input.articles[0].url,
        live_input.articles[0].preferred_image_urls[0],
        live_input.articles[1].url,
        live_input.articles[1].preferred_image_urls[0],
        live_input.articles[2].url,
        live_input.articles[2].preferred_image_urls[0],
    ]
    assert len(validated_children) == 3
    assert len(set(validated_children)) == 3
    audit = json.loads(artifact.files["live-acquisition.json"])
    assert audit["external_calls"] == {
        "news": 6,
        "source_pages": 3,
        "news_images": 3,
        "model": 0,
        "embedding": 0,
        "image_generation": 0,
        "wechat": 0,
        "wecom": 0,
    }
    assert [item["canonical_url"] for item in audit["articles"]] == [
        item.url for item in live_input.articles
    ]
    assert len({item["page_sha256"] for item in audit["articles"]}) == 3
    assert len({item["published_date"] for item in audit["articles"]}) == 3
    assert len({item["publisher"] for item in audit["articles"]}) == 3
    assert len({item["images"][0]["sha256"] for item in audit["articles"]}) == 3
    assert all(
        item["images"][0]["context_only_not_evidence"] is True
        and item["images"][0]["rights_status"] == "publish_permission_unverified"
        for item in audit["articles"]
    )

    child_sources: list[str] = []
    child_context_hashes: list[str] = []
    for role_ordinal, row in enumerate(audit["articles"], start=1):
        prefix = f"articles/{role_ordinal:02d}-{row['role']}"
        article = json.loads(artifact.files[f"{prefix}/article.json"])
        child_sources.append(article["sources"][0]["source_url"])
        child_context_hashes.append(article["news_context_media"]["items"][0]["sha256"])
        assert article["title"] == row["title"]
        assert article["sources"][0]["source_url"] == row["canonical_url"]
        assert article["news_context_media"]["items"][0]["source_page_url"] == row["canonical_url"]
        assert row["canonical_url"] in artifact.files[f"{prefix}/article-body.html"].decode()
        if row["role"] == "application_case":
            assert "涉农高校" in article["lead"]
    assert len(set(child_sources)) == 3
    assert len(set(child_context_hashes)) == 3


@pytest.mark.asyncio
async def test_live_theme_clusters_bind_six_sources_without_leakage() -> None:
    live_input = load_live_weekly_input(_THEME_INPUT)
    assert live_input.theme == "AI教育从普及走向真实学习场景"
    assert live_input.clusters is not None
    flat_sources = [source for cluster in live_input.clusters for source in cluster.sources]
    colors = (
        (18, 74, 112),
        (31, 112, 126),
        (46, 82, 166),
        (104, 70, 153),
        (28, 132, 101),
        (186, 105, 44),
    )
    selectors = (
        ".TRS_UEDITOR",
        ".content",
        "#detail",
        "#detail",
        "#detail",
        "#detail",
    )
    page_payloads = {
        source.url: _page(
            source.expected_title,
            source.expected_published_date.isoformat(),
            source.preferred_image_urls[0],
            selector=selector,
        )
        for source, selector in zip(flat_sources, selectors, strict=True)
    }
    image_payloads = {
        source.preferred_image_urls[0]: (
            "image/png" if source.preferred_image_urls[0].endswith(".png") else "image/jpeg",
            _image_bytes(
                "image/png" if source.preferred_image_urls[0].endswith(".png") else "image/jpeg",
                color,
            ),
        )
        for source, color in zip(flat_sources, colors, strict=True)
    }
    requests: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        requests.append(url)
        if url in page_payloads:
            return httpx.Response(
                200,
                headers={"Content-Type": "text/html; charset=utf-8"},
                content=page_payloads[url],
            )
        media_type, body = image_payloads[url]
        return httpx.Response(200, headers={"Content-Type": media_type}, content=body)

    transport = httpx.MockTransport(handler)
    artifact = await build_live_weekly_edition_artifact(
        live_input,
        page_fetcher=SafeHttpFetcher(Settings(), resolver=_public_resolver, transport=transport),
        image_fetcher=SafeSourceImageFetcher(
            Settings(), resolver=_public_resolver, transport=transport
        ),
        mobile_validation_factory=fixture_mobile_validation,
    )

    assert requests == [
        value for source in flat_sources for value in (source.url, source.preferred_image_urls[0])
    ]
    audit = json.loads(artifact.files["live-acquisition.json"])
    assert audit["version"] == "official-account-weekly-live-acquisition-audit-v3"
    assert audit["theme"] == live_input.theme
    assert audit["source_count"] == 6
    assert audit["external_calls"] == {
        "news": 12,
        "source_pages": 6,
        "news_images": 6,
        "model": 0,
        "embedding": 0,
        "image_generation": 0,
        "wechat": 0,
        "wecom": 0,
    }
    audit_sources = [source for row in audit["articles"] for source in row["sources"]]
    assert [source["relation"] for source in audit_sources] == [
        "primary",
        "supporting",
    ] * 3
    assert len({source["canonical_url"] for source in audit_sources}) == 6
    assert len({source["page_sha256"] for source in audit_sources}) == 6
    assert len({source["evidence_id"] for source in audit_sources}) == 6
    assert len({source["images"][0]["sha256"] for source in audit_sources}) == 6
    weekly_index = json.loads(artifact.files["weekly-index.json"])
    assert weekly_index["theme"] == live_input.theme
    assert weekly_index["live_source_count"] == 6
    manifest = json.loads(artifact.files["manifest.json"])
    assert manifest["theme"] == live_input.theme
    child_evidence: set[str] = set()
    for ordinal, row in enumerate(audit["articles"], start=1):
        prefix = f"articles/{ordinal:02d}-{row['role']}"
        article = json.loads(artifact.files[f"{prefix}/article.json"])
        assert article["title"] == row["editorial_title"]
        assert [source["source_url"] for source in article["sources"]] == [
            source["canonical_url"] for source in row["sources"]
        ]
        own_evidence = {source["evidence_id"] for source in row["sources"]}
        assert child_evidence.isdisjoint(own_evidence)
        child_evidence.update(own_evidence)
        assert {
            evidence
            for claim in article["claims"]
            if claim["kind"] == "external_fact"
            for evidence in claim["evidence_ids"]
        } == own_evidence
        assert [item["source_page_url"] for item in article["news_context_media"]["items"]] == [
            source["canonical_url"] for source in row["sources"]
        ]
        body = artifact.files[f"{prefix}/article-body.html"].decode()
        assert all(source["canonical_url"] in body for source in row["sources"])
        markdown = artifact.files[f"{prefix}/article.md"].decode()
        assert "publish_permission_unverified" not in markdown
        if row["role"] == "application_case":
            assert "不能证明主来源中的培训已经形成成功、可复制的应用成果" in markdown
    assert live_input.theme in artifact.files["index.html"].decode()
    assert all(source.url in artifact.files["index.html"].decode() for source in flat_sources)


def test_live_theme_input_rejects_relation_and_global_source_reuse(tmp_path: Path) -> None:
    payload = json.loads(_THEME_INPUT.read_text(encoding="utf-8"))
    payload["articles"][0]["sources"][1]["relation"] = "primary"
    invalid_relation = tmp_path / "invalid-relation.json"
    invalid_relation.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    with pytest.raises(ValueError, match="primary then supporting"):
        load_live_weekly_input(invalid_relation)

    payload = json.loads(_THEME_INPUT.read_text(encoding="utf-8"))
    payload["articles"][2]["sources"][1] = payload["articles"][1]["sources"][1]
    duplicate_source = tmp_path / "duplicate-source.json"
    duplicate_source.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    with pytest.raises(ValueError, match="globally distinct"):
        load_live_weekly_input(duplicate_source)

    payload = json.loads(_THEME_INPUT.read_text(encoding="utf-8"))
    payload["articles"][0]["sources"][0]["source_key"] = "xinhua-main"
    bad_official = tmp_path / "bad-official.json"
    bad_official.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    with pytest.raises(ValueError, match=r"registered source boundary|government authority"):
        load_live_weekly_input(bad_official)


def test_live_input_rejects_duplicate_source_and_unregistered_authority(tmp_path: Path) -> None:
    payload = json.loads(_INPUT.read_text(encoding="utf-8"))
    payload["articles"][1]["url"] = payload["articles"][0]["url"]
    duplicate = tmp_path / "duplicate.json"
    duplicate.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    with pytest.raises(ValueError, match="distinct"):
        load_live_weekly_input(duplicate)

    payload = json.loads(_INPUT.read_text(encoding="utf-8"))
    payload["articles"][0]["source_key"] = "xinhua-main"
    unregistered = tmp_path / "unregistered.json"
    unregistered.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    with pytest.raises(ValueError, match=r"registered source boundary|government authority"):
        load_live_weekly_input(unregistered)

    payload = json.loads(_INPUT.read_text(encoding="utf-8"))
    payload["articles"][2]["preferred_image_urls"] = ["https://example.com/cross-host.png"]
    cross_host = tmp_path / "cross-host.json"
    cross_host.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    with pytest.raises(ValueError, match="registered source boundary"):
        load_live_weekly_input(cross_host)

    payload = json.loads(_INPUT.read_text(encoding="utf-8"))
    payload["articles"][2]["expected_published_date"] = payload["articles"][1][
        "expected_published_date"
    ]
    duplicate_date = tmp_path / "duplicate-date.json"
    duplicate_date.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    with pytest.raises(ValueError, match="event dates"):
        load_live_weekly_input(duplicate_date)

    payload = json.loads(_INPUT.read_text(encoding="utf-8"))
    payload["articles"][2]["source_key"] = "xinhua-main"
    payload["articles"][2]["url"] = (
        "https://www.news.cn/20260829/another-distinct-application/c.html"
    )
    payload["articles"][2]["preferred_image_urls"] = [
        "https://www.news.cn/20260829/another-distinct-application/image.png"
    ]
    duplicate_publisher = tmp_path / "duplicate-publisher.json"
    duplicate_publisher.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    with pytest.raises(ValueError, match="publishers"):
        load_live_weekly_input(duplicate_publisher)


@pytest.mark.asyncio
async def test_live_page_and_image_failures_abort_without_fallback() -> None:
    live_input = load_live_weekly_input(_INPUT)
    settings = Settings()
    page_calls: list[str] = []

    def missing_page(request: httpx.Request) -> httpx.Response:
        page_calls.append(str(request.url))
        return httpx.Response(404)

    with pytest.raises(PermanentFetchError):
        await acquire_live_weekly_news(
            live_input,
            page_fetcher=SafeHttpFetcher(
                settings,
                resolver=_public_resolver,
                transport=httpx.MockTransport(missing_page),
            ),
            image_fetcher=SafeSourceImageFetcher(
                settings,
                resolver=_public_resolver,
                transport=httpx.MockTransport(lambda _request: httpx.Response(500)),
            ),
        )
    assert page_calls == [live_input.articles[0].url]

    first = live_input.articles[0]
    page_body = _page(
        first.expected_title,
        first.expected_published_date.isoformat(),
        first.preferred_image_urls[0],
        selector=".TRS_UEDITOR",
    )
    image_calls: list[str] = []

    def found_page(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            headers={"Content-Type": "text/html; charset=utf-8"},
            content=page_body,
        )

    def missing_image(request: httpx.Request) -> httpx.Response:
        image_calls.append(str(request.url))
        return httpx.Response(404)

    with pytest.raises(PermanentFetchError):
        await acquire_live_weekly_news(
            live_input,
            page_fetcher=SafeHttpFetcher(
                settings,
                resolver=_public_resolver,
                transport=httpx.MockTransport(found_page),
            ),
            image_fetcher=SafeSourceImageFetcher(
                settings,
                resolver=_public_resolver,
                transport=httpx.MockTransport(missing_image),
            ),
        )
    assert image_calls == [first.preferred_image_urls[0]]


def test_live_excerpts_keep_complete_units_and_drop_photo_caption_noise() -> None:
    source = """
    机器人会跳舞，也能跑步，但真正进入产业场景还需要真实数据与稳定任务。
    2026年8月26日，某队机器人参加比赛。新华社记者 测试 摄
    “产业从技术突破迈向场景贯通，相关产品正在进入更多可验证的真实流程。
    ”小朋友在现场完成一次交互体验，并把操作过程记录下来。
    新华社发（测试摄）
    家庭阅读这类新闻时，可以继续核对能力边界、失败处理与数据来源。
    后续观察应保留原始链接、发布日期和变化记录，避免用一次演示替代长期结果。
    学校可以先设计可重复的小任务，再记录不同条件下的执行结果。
    教师与学生需要分别标记现象、证据和尚未得到验证的推测。
    课程实施过程应说明工具能做什么，也要如实保留尚未解决的问题。
    只有把结果放回原始场景继续检验，一次体验才可能变成可传递的方法。
    """

    excerpts = _source_excerpts(source)

    assert len(excerpts) == 4
    assert all(item.endswith("。") for item in excerpts)
    assert all("记者" not in item and "新华社发" not in item for item in excerpts)
    assert all(item.count("“") == item.count("”") for item in excerpts)
    assert "某队机器人参加比赛" not in "".join(excerpts)
    assert "机器人。" not in "".join(excerpts)
    assert "新华社。" not in "".join(excerpts)


def test_live_excerpts_drop_page_chrome_and_event_roster_boilerplate() -> None:
    source = """
    教师AI训练营探索科普教育公益新模式
    发布日期：2026-08-03 浏览次数
    训练营围绕人工智能基础、课堂任务设计和项目复盘组织连续课程。
    中国海洋大学党委书记李明，共青团山东省委副书记盛夏等出席开班仪式。
    海尔集团党委书记、董事局主席、首席执行官周云杰致欢迎辞。
    教师先从真实教学问题出发拆解任务，再用工具生成可检查的中间结果。
    每个小组保留输入条件、失败记录和修改依据，便于回到课堂继续验证。
    培训安排了案例研讨、动手实践和同伴互评，强调过程证据而非一次展示。
    课程结束后，教师还要把方案带回学校试用，并记录学生反馈和约束条件。
    后续评估关注任务能否复现、教师能否解释工具边界，以及学生是否保留判断权。
    """

    excerpts = _source_excerpts(source)
    combined = "".join(excerpts)

    assert "发布日期" not in combined
    assert "浏览次数" not in combined
    assert "出席开班仪式" not in combined
    assert "致欢迎辞" not in combined
    assert "真实教学问题" in combined
    assert "动手实践" in combined


def test_live_excerpts_prioritize_substantive_teacher_training_method() -> None:
    source = """
    训练营由多家单位共同组织，为教师提供人工智能基础课程和应用体验。
    课程介绍了相关政策背景，并说明了基层学校目前面对的资源条件。
    首期培训邀请多所院校专家，为来自不同地区的一线教师提供系统性培训。
    教师们不仅能够学习如何借助AI设计跨学科课程，搭建属于自己的教学智能体，同时也将走进真实应用场景完成实操。
    每个小组还会记录任务输入、修改过程和失败原因，方便回到课堂复盘。
    培训结束后，教师需要结合本校条件调整方案，再观察学生的实际反馈。
    后续跟踪将关注课程是否可以重复实施，以及工具边界是否得到清晰解释。
    家庭和学校都需要把展示效果与真实学习结果分开记录。
    """

    excerpts = _source_excerpts(
        source,
        prioritized_terms=("设计跨学科课程", "教学智能体"),
    )

    assert "设计跨学科课程" in excerpts[-1]
    assert "教学智能体" in excerpts[-1]
