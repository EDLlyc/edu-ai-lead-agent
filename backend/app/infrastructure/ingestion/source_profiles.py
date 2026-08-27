from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from uuid import NAMESPACE_URL, UUID, uuid5

from app.domain.editorial_relevance import SCIENCE_TECH_EDITORIAL_RULE_VERSION
from app.domain.enums import SourceTier
from app.domain.value_objects import stable_key


@dataclass(frozen=True, slots=True)
class SourceSeed:
    slug: str
    display_name: str
    organization_type: str
    tier: SourceTier
    connector_key: str
    entry_url: str
    allowed_hosts: tuple[str, ...]
    allowed_path_prefixes: tuple[str, ...]
    robots_status: str
    rate_limit_seconds: float
    owner: str = "content-operations"
    cadence: str = "daily"
    timezone: str = "Asia/Shanghai"
    language: str = "zh-CN"
    connector_version: str = "1.0.0"
    parser_version: str = "1.0.0"
    relevance_rule_version: str | None = SCIENCE_TECH_EDITORIAL_RULE_VERSION
    allow_http_fallback: bool = False
    topic_priority_policy: str | None = None

    @property
    def source_id(self) -> UUID:
        return uuid5(NAMESPACE_URL, f"edu-ai-source:{self.slug}")

    @property
    def config_fingerprint(self) -> str:
        data = asdict(self)
        data["tier"] = self.tier.value
        return stable_key(json.dumps(data, sort_keys=True, ensure_ascii=False))

    @property
    def source_version_id(self) -> UUID:
        return uuid5(self.source_id, self.config_fingerprint)


SOURCE_SEEDS: tuple[SourceSeed, ...] = (
    SourceSeed(
        "china-government-policy",
        "中国政府网最新政策",
        "government",
        SourceTier.A,
        "gov_cn_policy_v1",
        "https://www.gov.cn/zhengce/zuixin/ZUIXINZHENGCE.json",
        ("www.gov.cn",),
        ("/zhengce/",),
        "allowed",
        2.0,
    ),
    SourceSeed(
        "bnu-news",
        "北京师范大学新闻网",
        "education_institution",
        SourceTier.A,
        "bnu_news_v1",
        "https://news.bnu.edu.cn/",
        ("news.bnu.edu.cn",),
        ("/",),
        "manual_review",
        3.0,
        connector_version="1.0.1",
        parser_version="1.0.1",
    ),
    SourceSeed(
        "cas-research",
        "中国科学院科研进展",
        "research_organization",
        SourceTier.A,
        "cas_research_v1",
        "https://www.cas.cn/syky/",
        ("www.cas.cn",),
        ("/",),
        "manual_review",
        3.0,
        connector_version="1.0.1",
        parser_version="1.0.1",
    ),
    SourceSeed(
        "sensetime-news",
        "商汤科技新闻中心",
        "ai_company",
        SourceTier.A,
        "sensetime_news_v1",
        "https://www.sensetime.com/cn/news",
        ("www.sensetime.com", "sensetime.com"),
        ("/cn/news",),
        "allowed",
        3.0,
    ),
    SourceSeed(
        "xinhua-tech",
        "新华网科技",
        "authoritative_media",
        SourceTier.B,
        "xinhua_tech_v1",
        "https://www.news.cn/tech/",
        ("www.news.cn", "news.cn"),
        ("/",),
        "allowed",
        2.0,
    ),
    SourceSeed(
        "gmw-education",
        "光明网教育",
        "authoritative_media",
        SourceTier.B,
        "gmw_education_v1",
        "https://edu.gmw.cn/",
        ("edu.gmw.cn", "www.gmw.cn", "gmw.cn"),
        ("/",),
        "allowed_with_path_exclusions",
        3.0,
        connector_version="1.0.1",
        parser_version="1.0.1",
    ),
    SourceSeed(
        "stdaily-tech",
        "科技日报",
        "authoritative_media",
        SourceTier.B,
        "stdaily_tech_v1",
        "https://www.stdaily.com/",
        ("www.stdaily.com", "stdaily.com"),
        ("/",),
        "allowed",
        3.0,
        connector_version="1.0.1",
        parser_version="1.0.1",
    ),
    SourceSeed(
        "chinanews-education",
        "中国新闻网教育",
        "authoritative_media",
        SourceTier.B,
        "chinanews_education_v1",
        "https://www.chinanews.com.cn/edu/",
        ("www.chinanews.com.cn", "chinanews.com.cn"),
        ("/",),
        "allowed_with_path_exclusions",
        3.0,
    ),
    SourceSeed(
        "moe-science-news",
        "教育部科学新闻",
        "government",
        SourceTier.A,
        "moe_news_v1",
        "https://www.moe.gov.cn/jyb_xwfb/",
        ("www.moe.gov.cn",),
        ("/jyb_xwfb/",),
        "manual_review",
        2.0,
        connector_version="1.0.0",
        parser_version="1.0.0",
        allow_http_fallback=True,
        topic_priority_policy="moe-science-top1-v1",
    ),
    SourceSeed(
        "xinhua-education",
        "新华教育",
        "authoritative_media",
        SourceTier.B,
        "xinhua_education_v1",
        "https://education.news.cn/index.htm",
        ("education.news.cn",),
        ("/",),
        "allowed",
        3.0,
    ),
    SourceSeed(
        "china-government-news",
        "中国政府网要闻",
        "government",
        SourceTier.A,
        "gov_cn_yaowen_v1",
        "https://www.gov.cn/yaowen/liebiao/YAOWENLIEBIAO.json",
        ("www.gov.cn",),
        ("/yaowen/liebiao/",),
        "allowed",
        2.0,
        topic_priority_policy="gov-cn-qualified-science-tech-v1",
    ),
)

# These profiles have fixture/connector approval but are deliberately excluded from SOURCE_SEEDS.
# A future activation must pass a production-safe bounded live entry + one-detail smoke first.
PENDING_SOURCE_SEEDS: tuple[SourceSeed, ...] = (
    SourceSeed(
        "cast-science-education",
        "中国科协科普与科学教育",
        "science_organization_media",
        SourceTier.B,
        "cast_science_education_v1",
        "https://www.cast.org.cn/kp/",
        ("www.cast.org.cn",),
        ("/kp/", "/xw/"),
        "manual_review",
        5.0,
    ),
    SourceSeed(
        "edsurge-ai-education",
        "EdSurge AI Education",
        "specialist_education_media",
        SourceTier.B,
        "edsurge_ai_education_v1",
        "https://www.edsurge.com/coverage-areas/artificial-intelligence",
        ("www.edsurge.com",),
        ("/coverage-areas/artificial-intelligence", "/news/"),
        "allowed_with_path_exclusions",
        4.0,
        timezone="UTC",
        language="en",
    ),
)

TERMS_REVIEWED_AT = datetime(2026, 8, 13, tzinfo=UTC)
