"""Aggregate three finalized V2 handoffs into one local weekly edition."""

# ruff: noqa: RUF001 -- Full-width Chinese punctuation is intentional fixture copy.

from __future__ import annotations

import argparse
import asyncio
import json
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from functools import lru_cache
from hashlib import sha256
from io import BytesIO
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Literal, cast
from uuid import UUID, uuid5
from zoneinfo import ZoneInfo

from PIL import Image, ImageDraw, ImageOps

from app.application.ports.official_account_local import OfficialAccountMediaResult
from app.application.services.official_account_editor_handoff_v2 import (
    EditorHandoffV2Artifact,
    bind_editor_handoff_v2_mobile_validation,
    build_editor_handoff_v2_artifact,
)
from app.application.services.official_account_weekly_edition import (
    WeeklyEditionArtifact,
    bind_weekly_child,
    build_weekly_edition_artifact,
    finalized_v2_child_from_artifact,
    load_finalized_v2_child,
    write_weekly_edition_artifact,
)
from app.domain.editorial_relevance import (
    ScienceTechContentSignal,
    ScienceTechEditorialCohort,
)
from app.domain.image_provider_input import normalize_image_provider_reference
from app.domain.official_account_editor_handoff_v2 import (
    BodyVisualLineage,
    BodyVisualReferenceProjection,
    EditorHandoffMobileValidation,
    EditorHandoffRelease,
    fingerprint_v2,
)
from app.domain.official_account_local import (
    ArticleBlock,
    ArticleBulletListBlock,
    ArticleImageBlock,
    ArticlePackage,
    ArticleParagraphBlock,
    ArticleQuoteBlock,
    ArticleSection,
    article_package_fingerprint,
    fingerprint,
)
from app.domain.official_account_weekly_edition import (
    WEEKLY_EDITION_ROLE_ORDER,
    WeeklyArticleRole,
    WeeklyEditionSchedule,
    WeeklyEditionSelection,
    WeeklyGovernedCandidate,
    select_weekly_articles,
    weekly_selection_from_projection,
)
from app.domain.topic_selection import (
    TopicCandidate,
    TopicScoringConfig,
    score_topic_candidate,
)
from app.official_account_editor_handoff_v2_demo import build_demo_artifact

_FIXTURE_NAMESPACE = UUID("629c01ca-3fd3-42da-8302-5d38e94d338d")
_REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
_CONTENT_ASSET_ROOT = _REPOSITORY_ROOT / "docs/portfolio/assets/content-showcase"
_BRAND_ASSET_ROOT = _REPOSITORY_ROOT / "private/brand-materials/05-visual-assets"
_BODY_BACKGROUNDS = (
    _CONTENT_ASSET_ROOT / "xiaosai-science-observe-publication-v2.jpg",
    _CONTENT_ASSET_ROOT / "xiaosai-science-experiment-publication-v2.jpg",
    _CONTENT_ASSET_ROOT / "xiaosai-science-reflect-publication-v2.jpg",
)
_CONTEXT_BACKGROUNDS = (
    _CONTENT_ASSET_ROOT / "xiaosai-science-observe-publication-v2.jpg",
    _CONTENT_ASSET_ROOT / "xiaosai-science-reflect-publication-v2.jpg",
)
_COVER_BACKGROUNDS = {
    WeeklyArticleRole.OFFICIAL_ANCHOR: (
        _CONTENT_ASSET_ROOT / "xiaosai-science-inquiry-cover-publication-v2.jpg"
    ),
    WeeklyArticleRole.INDUSTRY_TREND: (
        _CONTENT_ASSET_ROOT / "xiaosai-science-reflect-publication-v2.jpg"
    ),
    WeeklyArticleRole.APPLICATION_CASE: (
        _CONTENT_ASSET_ROOT / "xiaosai-science-experiment-publication-v2.jpg"
    ),
}
_IP_REFERENCE_GROUPS = (
    (_BRAND_ASSET_ROOT / "小赛和赛先生讨论.png",),
    (_BRAND_ASSET_ROOT / "小赛和赛先生思考.png",),
    (_BRAND_ASSET_ROOT / "赛先生小赛-双向奔赴.png",),
)
_ROLE_PALETTES = {
    WeeklyArticleRole.OFFICIAL_ANCHOR: (20, 86, 122),
    WeeklyArticleRole.INDUSTRY_TREND: (43, 92, 170),
    WeeklyArticleRole.APPLICATION_CASE: (25, 135, 113),
}
_BASE_BLOCK_BINDINGS = (
    (0, 0, "dcc5c01df629bc142f2cf8dab6a86d87563e846af994ef9fdb50d1515de2481d"),
    (2, 0, "105452d499249f7b2abcb7b4d856fbbe3eb551d8de28f0a022222f631444b125"),
    (3, 0, "cefb010bc1fd2f049f78c930631c615bc597d2d41c2d27d81eb7b8424c3a8089"),
)
_PORTABLE_BASE_ARTIFACT: EditorHandoffV2Artifact | None = None
_FIXTURE_COPY = {
    WeeklyArticleRole.OFFICIAL_ANCHOR: (
        "本地样例｜从权威信息到家庭科创判断",
        "本地确定性样例：演示官方主推文章的独立排版与交付，不代表实时新闻采集。",
        "这是一篇离线合成的官方主推槽位样例，用于验证每周三篇文章的独立生成、配图与交付结构。",
        "本地样例只验证流程：真实运行仍须绑定当周已治理的官方原文与完整证据。",
    ),
    WeeklyArticleRole.INDUSTRY_TREND: (
        "本地样例｜AI 教育行业趋势如何判断",
        "本地确定性样例：演示行业趋势文章的独立排版与交付，不代表实时新闻采集。",
        "这是一篇离线合成的行业趋势槽位样例，用于验证趋势信号与小赛视觉资产能够形成独立文章。",
        "本地样例不声称调用新闻、模型或生图服务，真实内容仍以持久化证据为准。",
    ),
    WeeklyArticleRole.APPLICATION_CASE: (
        "本地样例｜把科创方法带进家庭实践",
        "本地确定性样例：演示应用案例文章的独立排版与交付，不代表实时新闻采集。",
        "这是一篇离线合成的应用案例槽位样例，用于验证学校、课程与家庭实践方向的独立文章交付。",
        "本地样例只说明自动化结构，不把品牌资料或模拟内容当成外部事实证据。",
    ),
}
_FIXTURE_SECTION_COPY = {
    WeeklyArticleRole.OFFICIAL_ANCHOR: (
        (
            "先确认原文边界，再讨论它与家庭科创的关系",
            (
                "7月22日，全国基础教育工作会议在北京召开。离线样例不延伸会议细节，只演示一条基本规则：先标出发布主体、时间与原文边界，再把“已经确认的事实”和“面向家庭的解释”分开。",
                "阅读权威信息可以依次做四件事：找到原始发布页，核对发布日期，圈出明确动作，记录尚未说明的部分。这样处理不是为了让家长研究政策文本，而是避免一段转述在传播中不断增加原文没有的结论。",
                "当信息落到家庭场景时，可以把宏观表达转换成一个可观察的问题。例如，不急着问“孩子还缺什么课”，先问“最近哪一次提问值得继续追踪”。解释只有回到真实行为，才不会变成新的焦虑清单。",
                "先读原文，再做解释；先说明确定范围，再给家庭建议。",
            ),
        ),
        (
            "用来源卡片拆开事实、判断与行动建议",
            (
                "一张最小来源卡片只需要四栏：谁发布、何时发布、原文说了什么、原文没有说什么。最后一栏尤其重要，它提醒写作者不要把愿景当成已经发生的结果，也不要把局部案例扩写成普遍结论。",
                "接着再写判断层。判断可以有立场，但要能回到前面的事实栏逐项核对。若新材料改变了判断，也应保留修改原因。对孩子来说，这种公开修正比“第一次就答对”更能示范可靠思考。",
                "尊重好奇心与坚持证据并不冲突。温和的表达负责降低理解门槛，可靠资料负责守住事实边界；两者放在同一张卡片里，家长才容易看清哪些内容可以直接引用，哪些只是当前建议。",
                "每一条家庭建议前，都应能回答：它依据哪一句原文，又增加了哪一步解释？",
            ),
        ),
        (
            "把政策语言转换成一项本周可验证的小行动",
            (
                "教育部召开新闻发布会介绍《“人工智能+教育”行动计划》有关情况。离线样例只保留这条已绑定证据的事实句；至于工具怎样进入具体家庭，应继续区分官方信息、产品能力与个人使用建议。",
                "转化时可以采用“小目标、短周期、可复盘”的办法：本周只选一个孩子真正关心的问题，允许工具帮助整理资料，但把观察、选择与解释留给孩子。这样既回应新工具，也不会让工具替代学习主体。",
                "复盘时记录四句话：我们原来怎样理解，查到了哪些可靠信息，做了什么尝试，下一次准备改变什么。它把观察、提问、验证与复盘串成一个闭环，也让建议的效果能够被家庭自己核对。",
                "官方信息提供方向，家庭行动仍需小步验证，不能把口号直接当成效果。",
            ),
        ),
        (
            "建立一份可以持续更新的家庭信息账本",
            (
                "信息账本不追求收藏越多越好，而是保留每次判断的来路。孩子可以用自己的话复述原文，家长补充链接与日期；遇到不同说法时，再一起比较来源、证据和适用范围。表达本身就是一次核对。",
                "更稳妥的反馈也应落在过程上：这次找到了原始来源，这个判断还缺证据，这条建议已经完成一次验证。具体反馈能保护好奇心，也能让严谨不再等同于压力。",
                "本地样例的目标不是替你完成一次政策解读，而是验证“权威原文—边界说明—家庭行动—复盘记录”的完整文章链路。",
            ),
        ),
    ),
    WeeklyArticleRole.INDUSTRY_TREND: (
        (
            "热闹不等于趋势，先看需求是否真实存在",
            (
                "7月22日，全国基础教育工作会议在北京召开。把这条已绑定事实放进行业观察时，重点不是借会议名称替任何产品背书，而是提醒我们：教育需求来自真实场景，行业判断必须与学校、教师和家庭面对的问题相连接。",
                "一个趋势至少需要四类信号相互印证：持续出现的需求、可重复的产品能力、愿意长期使用的用户，以及能够解释的学习结果。只有发布会、融资消息或一次演示，最多构成线索，还不能单独构成趋势。",
                "判断新产品时，可以把“看起来很强”改写成三个问题：它替谁节省了哪一步，它把哪项决定留给了人，它的效果如何被复核。问题越具体，越容易发现能力边界，也越不容易被宣传节奏带着走。",
                "先确认真实需求，再观察产品供给；先收集连续信号，再形成趋势判断。",
            ),
        ),
        (
            "把行业信号放进同一张观察表",
            (
                "观察表可以按需求、产品、使用、结果四列记录。需求列写场景和频率，产品列写已经可用的能力，使用列写谁在什么条件下持续使用，结果列只放能够复核的变化。四列缺一时，结论就应保留不确定性。",
                "如果一项能力在演示中有效、在真实流程中却需要大量人工补位，不必急着判定失败。更有价值的问题是：补位发生在哪里，成本能否下降，失败能否被及时发现。趋势常常藏在这些重复出现的摩擦里。",
                "行业文章也要把事实与观点分层。来源材料回答“发生了什么”，分析回答“为什么值得关注”，品牌表达负责让读者更容易理解，但不能反过来替外部事实提供证明。",
                "每一个“正在成为趋势”的判断，都应同时给出支持信号和反向证据。",
            ),
        ),
        (
            "观察人工智能进入教育的三条边界",
            (
                "教育部召开新闻发布会介绍《“人工智能+教育”行动计划》有关情况。这条事实能够说明议题受到关注，却不能直接证明某个产品有效。具体判断仍要回到产品实际能力、使用条件与可核对结果。",
                "第一条边界是任务归属：整理、检索与反馈可以被辅助，目标选择和价值判断仍由人负责。第二条边界是数据来源：训练材料、学生信息和输出用途需要被说明。第三条边界是失败处理：系统不确定时必须允许停止和回退。",
                "把三条边界放进产品观察后，讨论会从“要不要用”转向“在哪一步用、由谁确认、出了问题怎样恢复”。这类问题不够炫目，却更接近学校和家庭真正需要承担的成本。",
                "能力增长值得关注，责任边界同样是行业成熟度的一部分。",
            ),
        ),
        (
            "用连续四周的信号代替一次性的结论",
            (
                "行业变化速度快，单次判断需要设置复核日期。每周只更新新增事实、被推翻的假设和仍未解决的问题；四周后再看，哪些信号持续出现，哪些只是短暂噪声，趋势轮廓会比即时评论清楚得多。",
                "写作时也应保留变化记录。与其删除旧判断，不如说明它为何被修正。能够公开修正的行业观察，才真正把证据放在立场之前，也能帮助读者形成自己的判断。",
                "本地样例只验证“需求—产品—使用—结果—边界—复核”的趋势文章结构，"
                "不声称已经调用实时新闻、模型、Embedding 或生图服务。",
            ),
        ),
    ),
    WeeklyArticleRole.APPLICATION_CASE: (
        (
            "从一个孩子真正提出的问题开始设计活动",
            (
                "7月22日，全国基础教育工作会议在北京召开。离线案例不扩写会议内容，而是示范怎样把已确认的信息放回一个小场景：活动设计先听见孩子的问题，再决定材料和步骤，而不是先买一套器材再寻找使用理由。",
                "可以请孩子在一周里记录三个“我想知道”：窗边的影子为什么移动，冰块放在哪里融化更快，植物朝向为什么不同。周末只选其中一个，确保材料随手可得、变量容易比较、过程能够在半小时内完成。",
                "家长的第一项任务不是准备答案，而是帮助缩小问题。把“为什么会这样”改成“我们先比较哪两种情况”，把“我要证明”改成“我准备观察什么”。问题变小以后，孩子才真正拥有设计和修改步骤的空间。",
                "活动从真实问题出发，材料服务于验证，成年人只负责守住安全与节奏。",
            ),
        ),
        (
            "用四格记录表把观察变成证据",
            (
                "四格记录表分别写材料、条件、看到的变化和新的疑问。不会写字的孩子可以画图或口述，重点不是版面整齐，而是让另一个人能够看懂：当时做了什么，结果为什么支持或推翻原来的猜想。",
                "第一次结果不明显时，不急着增加更多步骤。先检查是否同时改变了多个条件，观察时间是否足够，记录是否遗漏。每次只修正一处，孩子会逐渐理解实验不是表演成功，而是让不同解释接受检验。",
                "反馈也尽量具体：这张图把前后变化画清楚了，这次只改变了一个条件，这个结论还需要再做一次。它既保护探索热情，也让“尊重事实”成为孩子能够执行的动作。",
                "记录不是活动后的装饰，而是孩子重新检查自己想法的工具。",
            ),
        ),
        (
            "让人工智能做助手，不替孩子完成判断",
            (
                "教育部召开新闻发布会介绍《“人工智能+教育”行动计划》有关情况。离线案例只引用这条证据事实，并把工具使用限制在明确任务里：帮助整理关键词、生成记录表或比较表达，不替孩子观察现场。",
                "使用前先约定分工：孩子负责提出问题、选择条件和描述现象，工具负责整理已有记录，家长负责核对来源与安全。若工具给出无法解释的结论，就把它标成“待验证”，而不是直接写进结果。",
                "活动结束后让孩子用四句话复盘：我原来怎么想，我实际看到了什么，哪条建议帮到了我，下一次准备改什么。这样既能学习使用工具，也能看见判断权始终掌握在自己手里。",
                "工具可以缩短整理时间，但观察、选择和解释必须由孩子完成。",
            ),
        ),
        (
            "把一次活动沉淀为下一次可以复用的方法",
            (
                "完成后可以请孩子讲给另一位家人听，或把步骤画成三张图。听众如果追问“为什么这样做”，正好帮助发现被跳过的条件。表达不是成果展示的最后一步，它本身就是复盘和再次验证。",
                "家庭还可以保留一个小盒子，装入记录卡、失败样本和下一次问题。评价只看是否提出了清楚问题、留下了可核对记录、愿意根据结果修改想法，不把漂亮成品当成唯一标准。",
                "本地样例验证的是“问题—设计—记录—工具分工—表达复盘”的完整案例文章；真实发布仍须替换为当周已治理事件与对应的语义配图。",
            ),
        ),
    ),
}

_FIXTURE_VISUAL_BRIEFS = {
    WeeklyArticleRole.OFFICIAL_ANCHOR: (
        "小赛和赛先生陪孩子核对权威原文、发布日期与来源卡片，区分已确认事实和家庭解释。",
        "小赛和赛先生与孩子把官方信息转成一项可验证的小行动，并在桌面记录观察步骤。",
        "小赛和赛先生陪孩子整理来源、判断、行动和复盘记录，形成可以持续更新的信息账本。",
    ),
    WeeklyArticleRole.INDUSTRY_TREND: (
        "小赛和赛先生与孩子观察人工智能教育行业信号板，先核对真实需求再判断热度。",
        "小赛和赛先生陪孩子比较需求、产品、使用和结果四类信号，检查能力与责任边界。",
        "小赛和赛先生与孩子复盘连续四周的行业变化，区分持续趋势、反向证据和短期噪声。",
    ),
    WeeklyArticleRole.APPLICATION_CASE: (
        "小赛和赛先生从孩子真正提出的问题出发，共同选择材料并设计一个安全的小实验。",
        "小赛和赛先生陪孩子使用四格记录表观察条件和变化，让现场证据而不是工具代替判断。",
        "小赛和赛先生与孩子复盘活动步骤、失败样本和新问题，把一次实践沉淀成可复用方法。",
    ),
}


@dataclass(frozen=True, slots=True)
class _FixtureRoleVisual:
    ordinal: int
    scene_brief: str
    body: bytes
    body_sha256: str
    reference_body: bytes
    reference_public_ref: str
    reference_source_checksum: str
    reference_publication_checksum: str
    reference_input_checksum: str
    reference_characters: tuple[Literal["xiao-sai", "sai-xiansheng"], ...]


def _load_selection(path: Path) -> WeeklyEditionSelection:
    def reject_duplicates(pairs: list[tuple[str, object]]) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("weekly selection JSON contains a duplicate field")
            result[key] = value
        return result

    payload = json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=reject_duplicates)
    return weekly_selection_from_projection(payload)


def _parse_children(values: list[str]) -> dict[WeeklyArticleRole, Path]:
    if len(values) != 3:
        raise ValueError("weekly edition requires exactly three --child values")
    children: dict[WeeklyArticleRole, Path] = {}
    for value in values:
        role_value, separator, path_value = value.partition("=")
        if not separator or not path_value:
            raise ValueError("weekly child must use ROLE=/absolute/or/relative/path")
        role = WeeklyArticleRole(role_value)
        if role in children:
            raise ValueError("weekly child roles must be unique")
        children[role] = Path(path_value)
    if tuple(role.value for role in children) != WEEKLY_EDITION_ROLE_ORDER:
        raise ValueError("weekly children must be supplied in official/industry/application order")
    return children


def build_fixture_selection() -> WeeklyEditionSelection:
    """Create truthful synthetic governed inputs without acquiring live news."""

    schedule = WeeklyEditionSchedule()
    cutoff = datetime(2026, 8, 31, 9, tzinfo=ZoneInfo("Asia/Shanghai"))
    candidates = (
        _fixture_candidate(1, cutoff=cutoff, organization_type="government"),
        _fixture_candidate(
            2,
            cutoff=cutoff,
            organization_type="ai_company",
            cohort=ScienceTechEditorialCohort.FRONTIER_SCIENCE_TECHNOLOGY,
            signals=(ScienceTechContentSignal.PRODUCT_OR_SERVICE_RELEASE,),
            directions=("ai_theme_robotics_agent_safety_math_3d_hackathon",),
        ),
        _fixture_candidate(
            3,
            cutoff=cutoff,
            organization_type="education_institution",
            directions=("science_exploration_courses_and_camps",),
        ),
    )
    return select_weekly_articles(
        candidates,
        week_start=date(2026, 8, 31),
        cutoff=cutoff,
        schedule=schedule,
    )


async def build_fixture_children(
    *,
    browser_validations: dict[WeeklyArticleRole, EditorHandoffMobileValidation] | None = None,
) -> tuple[EditorHandoffV2Artifact, EditorHandoffV2Artifact, EditorHandoffV2Artifact]:
    """Derive three distinct local articles from frozen fixture bytes with zero providers."""

    base = await _build_portable_base_artifact()
    base_article = ArticlePackage.model_validate_json(base.files["article.json"])
    artifacts: list[EditorHandoffV2Artifact] = []
    for role in WeeklyArticleRole:
        role_visuals = _fixture_role_visuals(role)
        title, digest, lead, conclusion = _FIXTURE_COPY[role]
        article = base_article.model_copy(
            update={
                "title": title,
                "digest": digest,
                "lead": lead,
                "sections": _fixture_sections(
                    article=base_article,
                    role=role,
                    anchor_paths=frozenset(
                        (item.section_index, item.block_index) for item in base.body_visuals
                    ),
                    scene_briefs=(
                        role_visuals[0].scene_brief,
                        role_visuals[1].scene_brief,
                        role_visuals[2].scene_brief,
                    ),
                ),
                "conclusion": conclusion,
            }
        )
        article = _bind_fixture_media_selection(article=article, visuals=role_visuals)
        article = article.model_copy(
            update={"content_fingerprint": article_package_fingerprint(article)}
        )
        run_id = uuid5(_FIXTURE_NAMESPACE, role.value)
        run_request = fingerprint_v2("weekly-fixture-run", role.value, run_id)
        media = _fixture_media_rows(base=base, role=role, visuals=role_visuals)
        body_visuals = _fixture_body_visual_lineages(
            base=base,
            article=article,
            role=role,
            visuals=role_visuals,
        )
        release = EditorHandoffRelease(
            policy="quality_auto",
            kind="machine",
            input_fingerprint=fingerprint_v2(
                "weekly-fixture-release",
                role.value,
                article.content_fingerprint,
            ),
            gate_codes=base.release.gate_codes,
        )
        artifact = build_editor_handoff_v2_artifact(
            run_id=run_id,
            run_request_fingerprint=run_request,
            article=article,
            release=release,
            review=None,
            draft_resolved_fingerprint=fingerprint_v2(
                "weekly-fixture-draft",
                role.value,
                article.content_fingerprint,
            ),
            media=media,
            body_visuals=body_visuals,
            eligibility_checks=(),
        )
        if browser_validations is not None:
            artifact = bind_editor_handoff_v2_mobile_validation(
                artifact,
                browser_validations[role],
            )
        artifacts.append(artifact)
    return artifacts[0], artifacts[1], artifacts[2]


def _fixture_sections(
    *,
    article: ArticlePackage,
    role: WeeklyArticleRole,
    anchor_paths: frozenset[tuple[int, int]],
    scene_briefs: tuple[str, str, str],
) -> tuple[ArticleSection, ...]:
    """Make every synthetic article structurally distinct while preserving visual anchors."""

    section_copy = _FIXTURE_SECTION_COPY[role]
    if len(section_copy) != len(article.sections):
        raise ValueError("weekly fixture section copy is incomplete")
    sections: list[ArticleSection] = []
    for section_index, section in enumerate(article.sections):
        heading, replacement_copy = section_copy[section_index]
        replacements = iter(replacement_copy)
        blocks: list[ArticleBlock] = []
        for block_index, block in enumerate(section.blocks):
            if isinstance(block, ArticleImageBlock):
                ordinal = int(block.slot_key.removeprefix("body-"))
                blocks.append(block.model_copy(update={"alt_text": scene_briefs[ordinal]}))
            elif (section_index, block_index) in anchor_paths:
                blocks.append(block)
            elif isinstance(block, ArticleParagraphBlock):
                blocks.append(block.model_copy(update={"text": next(replacements)}))
            elif isinstance(block, ArticleBulletListBlock):
                prefix = next(replacements)
                blocks.append(
                    block.model_copy(
                        update={
                            "items": tuple(
                                f"{prefix}{ordinal}：{item}"
                                for ordinal, item in enumerate(block.items, start=1)
                            )
                        }
                    )
                )
            elif isinstance(block, ArticleQuoteBlock):
                blocks.append(block.model_copy(update={"text": next(replacements)}))
            else:  # pragma: no cover - ArticleBlock is exhaustively discriminated.
                raise TypeError("unsupported weekly fixture article block")
        if next(replacements, None) is not None:
            raise ValueError("weekly fixture section copy has unused text")
        sections.append(
            section.model_copy(
                update={
                    "heading": heading,
                    "blocks": tuple(blocks),
                }
            )
        )
    return tuple(sections)


async def _build_portable_base_artifact() -> EditorHandoffV2Artifact:
    """Bootstrap V2 from durable local assets, never an ignored historical output."""

    global _PORTABLE_BASE_ARTIFACT
    if _PORTABLE_BASE_ARTIFACT is not None:
        return _PORTABLE_BASE_ARTIFACT
    with TemporaryDirectory(prefix="official-account-weekly-fixture-") as temporary:
        root = Path(temporary)
        body_visual_root = root / "body-visuals"
        news_context_root = root / "news-context"
        _write_portable_body_visual_source(body_visual_root)
        _write_portable_context_source(news_context_root)
        _PORTABLE_BASE_ARTIFACT = await build_demo_artifact(
            news_context_directory=news_context_root,
            body_visual_directory=body_visual_root,
        )
    return _PORTABLE_BASE_ARTIFACT


def _write_portable_body_visual_source(root: Path) -> None:
    visuals = _fixture_role_visuals(WeeklyArticleRole.OFFICIAL_ANCHOR)
    (root / "assets").mkdir(parents=True)
    (root / "references").mkdir()
    rows: list[dict[str, object]] = []
    for visual, (section_index, block_index, block_fingerprint) in zip(
        visuals,
        _BASE_BLOCK_BINDINGS,
        strict=True,
    ):
        asset = f"assets/body-{visual.ordinal:02d}.jpg"
        reference_asset = f"references/reference-{visual.ordinal:02d}.jpg"
        (root / asset).write_bytes(visual.body)
        (root / reference_asset).write_bytes(visual.reference_body)
        rows.append(
            {
                "ordinal": visual.ordinal,
                "section_index": section_index,
                "block_index": block_index,
                "block_kind": "paragraph",
                "block_fingerprint": block_fingerprint,
                "scene_brief": visual.scene_brief,
                "asset": asset,
                "media_type": "image/jpeg",
                "byte_size": len(visual.body),
                "width": 1536,
                "height": 1024,
                "output_sha256": visual.body_sha256,
                "visible_characters": list(visual.reference_characters),
                "visibility_status": "passed_local_visual_inspection",
                "reference": {
                    "asset": reference_asset,
                    "public_ref": visual.reference_public_ref,
                    "role": "action_reference",
                    "characters": list(visual.reference_characters),
                    "source_checksum": visual.reference_source_checksum,
                    "publication_checksum": visual.reference_publication_checksum,
                    "input_version": "image-reference-input-v2-png-preserve-jpeg-normalize",
                    "input_checksum": visual.reference_input_checksum,
                },
            }
        )
    payload = {
        "schema_version": "official-account-editor-handoff-body-visual-source-v1",
        "catalog_version": "weekly-local-approved-ip-compositor-v1",
        "selection_execution": {
            "method": "deterministic_fixture_semantic",
            "reason_code": "approved_reference_exact_block_fixture_selection",
            "embedding_provider_calls": 0,
        },
        # The V2 bootstrap loader validates its historical source-map shape. These
        # counters describe the accepted reference-conditioned source family; this
        # weekly compositor itself performs zero provider calls and rebinds the final
        # child lineages to provider_execution=not_claimed below.
        "generation_execution": {
            "kind": "built_in_imagegen_reference_conditioned",
            "provider_call_claim": "authorized_local_generation_completed",
            "image_generation_calls": 3,
            "wechat_calls": 0,
            "wecom_calls": 0,
            "publish_calls": 0,
        },
        "visuals": rows,
    }
    (root / "visual-map.json").write_text(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")),
        encoding="utf-8",
    )


def _write_portable_context_source(root: Path) -> None:
    (root / "assets").mkdir(parents=True)
    source_urls = (
        "https://www.moe.gov.cn/jyb_xwfb/s6052/moe_838/202607/t20260722_1444692.html",
        "https://www.moe.gov.cn/fbh/live/2026/77927/tpwd/202604/t20260410_1433382.html",
    )
    rows: list[dict[str, object]] = []
    for ordinal, (background, source_url) in enumerate(
        zip(_CONTEXT_BACKGROUNDS, source_urls, strict=True)
    ):
        image = _load_fitted_rgb(background, (1200, 675), centering=(0.5, 0.5))
        draw = ImageDraw.Draw(image, "RGBA")
        draw.rounded_rectangle(
            (36, 36, 1164, 639),
            radius=28,
            outline=(255, 255, 255, 150),
            width=4,
        )
        body = _jpeg_bytes(image)
        relative = f"assets/news-{ordinal:02d}.jpg"
        (root / relative).write_bytes(body)
        rows.append(
            {
                "local_path": relative,
                "sha256": sha256(body).hexdigest(),
                "byte_size": len(body),
                "media_type": "image/jpeg",
                "width": 1200,
                "height": 675,
                "alt_text": "本地离线上下文示意图，不是新闻现场原图",
                "caption": "本地确定性视觉占位，仅帮助验证排版；不是新闻原图，也不构成事实证据。",
                "credit": "项目本地 fixture｜非新闻原图",
                "source_page_url": source_url,
            }
        )
    (root / "news-photo-provenance.json").write_text(
        json.dumps(
            {
                "version": "official-account-news-context-photo-provenance-v1",
                "photos": rows,
            },
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ),
        encoding="utf-8",
    )


@lru_cache(maxsize=3)
def _fixture_role_visuals(
    role: WeeklyArticleRole,
) -> tuple[_FixtureRoleVisual, _FixtureRoleVisual, _FixtureRoleVisual]:
    visuals: list[_FixtureRoleVisual] = []
    role_index = role.ordinal - 1
    for ordinal, scene_brief in enumerate(_FIXTURE_VISUAL_BRIEFS[role]):
        reference_group = (role_index + ordinal) % len(_IP_REFERENCE_GROUPS)
        source_paths = _IP_REFERENCE_GROUPS[reference_group]
        source_hashes = tuple(sha256(path.read_bytes()).hexdigest() for path in source_paths)
        source_checksum = fingerprint_v2(
            "weekly-approved-ip-reference-source-set-v1",
            tuple(source_hashes),
        )
        reference_body = _reference_publication_bytes(
            source_paths,
            palette=_ROLE_PALETTES[role],
            ordinal=ordinal,
        )
        reference_checksum = sha256(reference_body).hexdigest()
        normalized = normalize_image_provider_reference(reference_body)
        public_ref = fingerprint_v2(
            "weekly-approved-ip-reference-public-v1",
            role.value,
            ordinal,
            source_checksum,
            reference_checksum,
        )[:16]
        background = _BODY_BACKGROUNDS[(role_index + ordinal) % len(_BODY_BACKGROUNDS)]
        body = _compose_role_body(
            background=background,
            source_paths=source_paths,
            palette=_ROLE_PALETTES[role],
            role_ordinal=role_index,
            visual_ordinal=ordinal,
        )
        visuals.append(
            _FixtureRoleVisual(
                ordinal=ordinal,
                scene_brief=scene_brief,
                body=body,
                body_sha256=sha256(body).hexdigest(),
                reference_body=reference_body,
                reference_public_ref=public_ref,
                reference_source_checksum=source_checksum,
                reference_publication_checksum=reference_checksum,
                reference_input_checksum=normalized.sha256,
                reference_characters=("xiao-sai", "sai-xiansheng"),
            )
        )
    return visuals[0], visuals[1], visuals[2]


def _compose_role_body(
    *,
    background: Path,
    source_paths: tuple[Path, ...],
    palette: tuple[int, int, int],
    role_ordinal: int,
    visual_ordinal: int,
) -> bytes:
    canvas = _load_fitted_rgb(background, (1536, 1024), centering=(0.5, 0.5)).convert("RGBA")
    tint = Image.new("RGBA", canvas.size, (*palette, 28 + role_ordinal * 8))
    canvas = Image.alpha_composite(canvas, tint)
    draw = ImageDraw.Draw(canvas, "RGBA")
    character_on_right = (role_ordinal + visual_ordinal) % 2 == 0
    panel = (875, 56, 1480, 968) if character_on_right else (56, 56, 661, 968)
    draw.rounded_rectangle(panel, radius=56, fill=(250, 248, 239, 190))
    draw.rounded_rectangle(panel, radius=56, outline=(*palette, 210), width=6)
    draw.ellipse((90, 78, 210, 198), fill=(*palette, 190))
    draw.ellipse((226, 112, 286, 172), fill=(242, 166, 70, 210))
    layer = _combined_ip_layer(source_paths, target_height=760)
    maximum_width = panel[2] - panel[0] - 70
    if layer.width > maximum_width:
        layer = _scaled_layer(layer, maximum_width=maximum_width)
    x = panel[0] + (panel[2] - panel[0] - layer.width) // 2
    y = panel[3] - layer.height - 30
    canvas.alpha_composite(layer, (x, y))
    return _jpeg_bytes(canvas.convert("RGB"))


@lru_cache(maxsize=3)
def _compose_role_cover(role: WeeklyArticleRole) -> bytes:
    centering = {
        WeeklyArticleRole.OFFICIAL_ANCHOR: (0.62, 0.52),
        WeeklyArticleRole.INDUSTRY_TREND: (0.50, 0.48),
        WeeklyArticleRole.APPLICATION_CASE: (0.48, 0.55),
    }[role]
    canvas = _load_fitted_rgb(
        _COVER_BACKGROUNDS[role],
        (1923, 818),
        centering=centering,
    ).convert("RGBA")
    palette = _ROLE_PALETTES[role]
    draw = ImageDraw.Draw(canvas, "RGBA")
    draw.rounded_rectangle((56, 48, 670, 770), radius=48, fill=(248, 245, 235, 210))
    draw.rounded_rectangle((56, 48, 670, 770), radius=48, outline=(*palette, 225), width=6)
    draw.ellipse((116, 88, 246, 218), fill=(*palette, 190))
    draw.ellipse((264, 116, 334, 186), fill=(242, 166, 70, 210))
    source_paths = _IP_REFERENCE_GROUPS[role.ordinal - 1]
    layer = _combined_ip_layer(source_paths, target_height=620)
    if layer.width > 540:
        layer = _scaled_layer(layer, maximum_width=540)
    x = 92 + (540 - layer.width) // 2
    y = 744 - layer.height
    canvas.alpha_composite(layer, (x, y))
    return _jpeg_bytes(canvas.convert("RGB"))


def _reference_publication_bytes(
    source_paths: tuple[Path, ...],
    *,
    palette: tuple[int, int, int],
    ordinal: int,
) -> bytes:
    canvas = Image.new("RGBA", (1536, 1024), (247, 244, 234, 255))
    draw = ImageDraw.Draw(canvas, "RGBA")
    draw.ellipse((70, 70, 520, 520), fill=(*palette, 48))
    draw.ellipse((1110, 560, 1480, 930), fill=(242, 166, 70, 50 + ordinal * 8))
    layer = _combined_ip_layer(source_paths, target_height=850)
    if layer.width > 1320:
        layer = _scaled_layer(layer, maximum_width=1320)
    canvas.alpha_composite(
        layer,
        ((canvas.width - layer.width) // 2, canvas.height - layer.height - 20),
    )
    return _jpeg_bytes(canvas.convert("RGB"))


def _combined_ip_layer(source_paths: tuple[Path, ...], *, target_height: int) -> Image.Image:
    parts: list[Image.Image] = []
    part_height = target_height if len(source_paths) == 1 else int(target_height * 0.92)
    for path in source_paths:
        if not path.is_file() or path.is_symlink():
            raise ValueError("weekly approved IP reference asset is unavailable")
        with Image.open(path) as opened:
            opened.load()
            part = opened.convert("RGBA")
        alpha_box = part.getchannel("A").getbbox()
        if alpha_box is None:
            raise ValueError("weekly approved IP reference has no visible pixels")
        part = part.crop(alpha_box)
        width = max(1, round(part.width * part_height / part.height))
        parts.append(part.resize((width, part_height), Image.Resampling.LANCZOS))
    gap = 24 if len(parts) > 1 else 0
    layer = Image.new(
        "RGBA",
        (sum(part.width for part in parts) + gap * (len(parts) - 1), max(p.height for p in parts)),
        (0, 0, 0, 0),
    )
    x = 0
    for part in parts:
        layer.alpha_composite(part, (x, layer.height - part.height))
        x += part.width + gap
    return layer


def _scaled_layer(layer: Image.Image, *, maximum_width: int) -> Image.Image:
    height = max(1, round(layer.height * maximum_width / layer.width))
    return layer.resize((maximum_width, height), Image.Resampling.LANCZOS)


def _load_fitted_rgb(
    path: Path,
    size: tuple[int, int],
    *,
    centering: tuple[float, float],
) -> Image.Image:
    if not path.is_file() or path.is_symlink():
        raise ValueError("weekly local visual source asset is unavailable")
    with Image.open(path) as opened:
        opened.load()
        return ImageOps.fit(
            opened.convert("RGB"),
            size,
            method=Image.Resampling.LANCZOS,
            centering=centering,
        )


def _jpeg_bytes(image: Image.Image) -> bytes:
    output = BytesIO()
    image.save(
        output,
        format="JPEG",
        quality=90,
        optimize=True,
        progressive=False,
        exif=b"",
    )
    return output.getvalue()


def fixture_mobile_validation(artifact: EditorHandoffV2Artifact) -> EditorHandoffMobileValidation:
    """Build the binding object after an external zero-network browser check has passed."""

    return EditorHandoffMobileValidation(
        status="passed",
        content_fingerprint=artifact.content_fingerprint,
        body_sha256=sha256(artifact.body_html).hexdigest(),
        media_sha256s=tuple(item.sha256 for item in artifact.media),
        viewports=(320, 430),
        external_requests=0,
        copy_root_matches_body=True,
    )


def _fixture_candidate(
    suffix: int,
    *,
    cutoff: datetime,
    organization_type: str,
    cohort: ScienceTechEditorialCohort = (
        ScienceTechEditorialCohort.SCIENCE_TECHNOLOGY_EDUCATION_PRIORITY
    ),
    signals: tuple[ScienceTechContentSignal, ...] = (),
    directions: tuple[str, ...] = (),
) -> WeeklyGovernedCandidate:
    candidate = TopicCandidate(
        event_id=uuid5(_FIXTURE_NAMESPACE, f"event:{suffix}"),
        event_version_id=uuid5(_FIXTURE_NAMESPACE, f"event-version:{suffix}"),
        event_time=cutoff - timedelta(days=suffix),
        source_trust=0.9,
        source_diversity=4,
        ai_relevance=0.9,
        parent_relevance=0.9,
        communication_potential=0.9,
        editorial_priority=0.9,
        science_tech_editorial_cohort=cohort,
        science_tech_education_relevance=0.9,
        frontier_significance=0.9,
        science_tech_editorial_reason_codes=("explicit_science_technology_education",),
        science_tech_content_signals=signals,
        product_matrix_fit_v2=0.9,
        product_matrix_v2_direction_ids=directions,
        priority_title=f"本地治理样例 {suffix}",
        priority_summary="本地确定性候选，不代表实时新闻。",
    )
    score = score_topic_candidate(candidate, as_of=cutoff, config=TopicScoringConfig())
    return WeeklyGovernedCandidate(
        candidate=candidate,
        score=score,
        organization_type=organization_type,
        source_metadata_fingerprint=fingerprint_v2(
            "weekly-fixture-source-metadata",
            organization_type,
            suffix,
        ),
    )


def _bind_fixture_media_selection(
    *,
    article: ArticlePackage,
    visuals: tuple[_FixtureRoleVisual, _FixtureRoleVisual, _FixtureRoleVisual],
) -> ArticlePackage:
    selection = article.media_selection
    if selection is None or len(selection.assignments) != 3:
        raise ValueError("weekly fixture media-selection anchors are incomplete")
    assignments = tuple(
        assignment.model_copy(
            update={
                "candidate_ref": visual.reference_public_ref,
                "source_checksum": visual.reference_source_checksum,
                "publication_checksum": visual.reference_publication_checksum,
                "selection_method": "deterministic_tag",
                "similarity_band": None,
            }
        )
        for assignment, visual in zip(selection.assignments, visuals, strict=True)
    )
    rebound = selection.model_copy(
        update={
            "catalog_version": "weekly-local-approved-ip-compositor-v1",
            "catalog_fingerprint": fingerprint_v2(
                "weekly-local-approved-ip-compositor-v1",
                tuple(item.reference_public_ref for item in visuals),
                tuple(item.reference_publication_checksum for item in visuals),
            ),
            "assignments": assignments,
        }
    )
    return article.model_copy(update={"media_selection": rebound})


def _fixture_body_visual_lineages(
    *,
    base: EditorHandoffV2Artifact,
    article: ArticlePackage,
    role: WeeklyArticleRole,
    visuals: tuple[_FixtureRoleVisual, _FixtureRoleVisual, _FixtureRoleVisual],
) -> tuple[BodyVisualLineage, BodyVisualLineage, BodyVisualLineage]:
    lineages: list[BodyVisualLineage] = []
    for original, visual in zip(base.body_visuals, visuals, strict=True):
        block = article.sections[original.section_index].blocks[original.block_index]
        if not isinstance(block, ArticleParagraphBlock):
            raise ValueError("weekly fixture visual target block changed")
        block_fingerprint = fingerprint(
            "official-account-generated-visual-block-v1",
            original.section_index,
            original.block_index,
            original.block_kind,
            " ".join(block.text.split())[:480],
        )
        scene_brief_fingerprint = fingerprint_v2(
            "editor-handoff-body-visual-scene-brief-v1",
            original.section_index,
            original.block_index,
            original.block_kind,
            visual.scene_brief,
        )
        lineages.append(
            original.model_copy(
                update={
                    "block_fingerprint": block_fingerprint,
                    "scene_brief": visual.scene_brief,
                    "scene_brief_fingerprint": scene_brief_fingerprint,
                    "reference": BodyVisualReferenceProjection(
                        public_ref=visual.reference_public_ref,
                        catalog_version="weekly-local-approved-ip-compositor-v1",
                        role="action_reference",
                        character_labels=visual.reference_characters,
                        source_checksum=visual.reference_source_checksum,
                        publication_checksum=visual.reference_publication_checksum,
                        input_checksum=visual.reference_input_checksum,
                    ),
                    "selection_method": "deterministic_fixture_semantic",
                    "similarity_band": None,
                    "generation_kind": "frozen_reference_conditioned_fixture",
                    "provider_execution": "not_claimed",
                    "plan_fingerprint": fingerprint_v2(
                        "weekly-local-ip-composition-plan-v1",
                        role.value,
                        visual.ordinal,
                        block_fingerprint,
                        visual.reference_input_checksum,
                        visual.body_sha256,
                    ),
                    "output_sha256": visual.body_sha256,
                    "output_byte_size": len(visual.body),
                    "visible_character_labels": visual.reference_characters,
                    "visibility_status": "passed_local_visual_inspection",
                }
            )
        )
    return lineages[0], lineages[1], lineages[2]


def _fixture_media_rows(
    *,
    base: EditorHandoffV2Artifact,
    role: WeeklyArticleRole,
    visuals: tuple[_FixtureRoleVisual, _FixtureRoleVisual, _FixtureRoleVisual],
) -> tuple[tuple[OfficialAccountMediaResult, bytes], ...]:
    rows: list[tuple[OfficialAccountMediaResult, bytes]] = []
    for visual, lineage in zip(visuals, base.body_visuals, strict=True):
        rows.append(
            (
                OfficialAccountMediaResult(
                    local_media_id=f"weekly-fixture-{role.value}-body-{visual.ordinal}",
                    role="body",
                    ordinal=visual.ordinal,
                    media_url=f"/local/weekly-fixture-{role.value}-body-{visual.ordinal}",
                    media_type="image/jpeg",
                    byte_size=len(visual.body),
                    sha256=visual.body_sha256,
                    semantic_label=visual.scene_brief,
                    assigned_section_index=lineage.section_index,
                    selection_reason_code="approved_local_ip_exact_block_fixture",
                    selection_method="deterministic_tag",
                    alt_text=visual.scene_brief,
                    provenance_kind="deterministic_local_composition",
                    caption="按角色正文块确定性合成的小赛与赛先生场景图；运行时未调用生图服务。",
                ),
                visual.body,
            )
        )
    for item in (item for item in base.media if item.role == "context"):
        rows.append(
            (
                OfficialAccountMediaResult(
                    local_media_id=f"weekly-fixture-{role.value}-context-{item.ordinal}",
                    role="context",
                    ordinal=item.ordinal,
                    media_url=f"/local/weekly-fixture-{role.value}-context-{item.ordinal}",
                    media_type=item.media_type,
                    byte_size=item.byte_size,
                    sha256=item.sha256,
                    semantic_label=item.alt_text,
                    assigned_section_index=item.assigned_section_index,
                    alt_text=item.alt_text,
                    provenance_kind="fixture_context_placeholder",
                    source_page_url=item.source_page_url,
                    caption=item.caption,
                    credit=item.credit,
                    rights_status=item.rights_status,
                    context_only_not_evidence=item.context_only_not_evidence,
                ),
                base.files[item.path],
            )
        )
    cover = _compose_role_cover(role)
    rows.append(
        (
            OfficialAccountMediaResult(
                local_media_id=f"weekly-fixture-{role.value}-cover-0",
                role="cover",
                ordinal=0,
                media_url=f"/local/weekly-fixture-{role.value}-cover-0",
                media_type="image/jpeg",
                byte_size=len(cover),
                sha256=sha256(cover).hexdigest(),
                semantic_label=f"{role.value} 本地角色专属宽封面",
                provenance_kind="deterministic_local_composition",
            ),
            cover,
        )
    )
    return tuple(rows)


async def build_fixture_weekly_edition_artifact() -> WeeklyEditionArtifact:
    """Build the complete frozen three-article aggregate without external requests."""

    staged = await build_fixture_children()
    reports = {
        role: fixture_mobile_validation(artifact)
        for role, artifact in zip(WeeklyArticleRole, staged, strict=True)
    }
    finalized = await build_fixture_children(browser_validations=reports)
    selection = build_fixture_selection()
    children = tuple(
        finalized_v2_child_from_artifact(artifact, role=role)
        for role, artifact in zip(WeeklyArticleRole, finalized, strict=True)
    )
    bindings = tuple(
        bind_weekly_child(selected=selected, child=child)
        for selected, child in zip(selection.selected, children, strict=True)
    )
    return build_weekly_edition_artifact(
        selection=selection,
        schedule=WeeklyEditionSchedule(),
        children=(children[0], children[1], children[2]),
        bindings=(bindings[0], bindings[1], bindings[2]),
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--fixture",
        action="store_true",
        help="build the frozen zero-network local fixture instead of loading finalized children",
    )
    parser.add_argument("--selection-json", type=Path)
    parser.add_argument(
        "--child",
        action="append",
        help="ROLE=finalized-v2-directory; repeat in canonical role order",
    )
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    if args.fixture:
        if args.selection_json is not None or args.child is not None:
            parser.error("--fixture cannot be combined with --selection-json or --child")
        artifact = asyncio.run(build_fixture_weekly_edition_artifact())
    else:
        if args.selection_json is None or args.child is None:
            parser.error("--selection-json and exactly three --child values are required")
        selection = _load_selection(cast(Path, args.selection_json))
        paths = _parse_children(cast(list[str], args.child))
        schedule = WeeklyEditionSchedule()
        children = tuple(
            load_finalized_v2_child(paths[role], role=role)
            for role in (
                WeeklyArticleRole.OFFICIAL_ANCHOR,
                WeeklyArticleRole.INDUSTRY_TREND,
                WeeklyArticleRole.APPLICATION_CASE,
            )
        )
        artifact = build_weekly_edition_artifact(
            selection=selection,
            schedule=schedule,
            children=(children[0], children[1], children[2]),
            bindings=(
                bind_weekly_child(selected=selection.selected[0], child=children[0]),
                bind_weekly_child(selected=selection.selected[1], child=children[1]),
                bind_weekly_child(selected=selection.selected[2], child=children[2]),
            ),
        )
    target = write_weekly_edition_artifact(artifact, args.output_dir)
    print(target)
    print(f"zip_sha256={artifact.zip_sha256}")
    print(f"homepage_operator_status={artifact.homepage_operator_state.status.value}")
    print(f"operator_checklist={target / 'operator-publication-checklist.md'}")


if __name__ == "__main__":
    main()
