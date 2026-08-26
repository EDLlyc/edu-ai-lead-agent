from __future__ import annotations

# ruff: noqa: RUF001 -- Chinese punctuation is intentional in the article fixture.
from pathlib import Path
from uuid import UUID, uuid5

from app.application.ports.official_account_local import (
    OfficialAccountAuditRequest,
    OfficialAccountAuditResult,
    OfficialAccountCatalogMediaProvider,
    OfficialAccountDraftRequest,
    OfficialAccountDraftResult,
    OfficialAccountGenerationRequest,
    OfficialAccountGenerationResult,
    OfficialAccountMediaRequest,
    OfficialAccountMediaResult,
)
from app.application.services.official_account_local import (
    audit_request_fingerprint,
    generation_request_fingerprint,
)
from app.domain.official_account_local import (
    OFFICIAL_ACCOUNT_FIXTURE_ID,
    OFFICIAL_ACCOUNT_GENERATOR_PROMPT_V1_VERSION,
    OFFICIAL_ACCOUNT_GENERATOR_PROMPT_V2_VERSION,
    OFFICIAL_ACCOUNT_GENERATOR_PROMPT_V3_VERSION,
    OFFICIAL_ACCOUNT_GENERATOR_PROMPT_V4_VERSION,
    OFFICIAL_ACCOUNT_GENERATOR_PROMPT_V5_VERSION,
    OFFICIAL_ACCOUNT_GENERATOR_PROMPT_V7_VERSION,
    OFFICIAL_ACCOUNT_GENERATOR_PROMPT_VERSION,
    OFFICIAL_ACCOUNT_LOCAL_ADAPTER_V1_VERSION,
    OFFICIAL_ACCOUNT_LOCAL_ADAPTER_V2_VERSION,
    OFFICIAL_ACCOUNT_LOCAL_ADAPTER_V3_VERSION,
    OFFICIAL_ACCOUNT_LOCAL_ADAPTER_V4_VERSION,
    OFFICIAL_ACCOUNT_LOCAL_ADAPTER_V6_VERSION,
    OFFICIAL_ACCOUNT_LOCAL_ADAPTER_V7_VERSION,
    OFFICIAL_ACCOUNT_LOCAL_ADAPTER_VERSION,
    OFFICIAL_ACCOUNT_RULE_V1_VERSION,
    OFFICIAL_ACCOUNT_RULE_V2_VERSION,
    OFFICIAL_ACCOUNT_RULE_V3_VERSION,
    OFFICIAL_ACCOUNT_RULE_VERSION,
    ArticleBulletListBlock,
    ArticleParagraphBlock,
    ArticleQuoteBlock,
    GeneratedArticleClaim,
    GeneratedArticleDraft,
    GeneratedArticleSection,
    OfficialAccountAuditVerdict,
    OfficialAccountBrandContext,
    OfficialAccountEvidence,
    OfficialAccountSourceSnapshot,
    fingerprint,
)

_FIXTURE_NAMESPACE = UUID("8f778a3f-2edb-4b25-a3b3-87a6aa181fd8")
FIXTURE_EVIDENCE_ID = uuid5(_FIXTURE_NAMESPACE, "evidence")
FIXTURE_BRAND_CHUNK_ID = uuid5(_FIXTURE_NAMESPACE, "brand")
FIXTURE_IMAGE_RELATIVE_PATH = Path(
    "docs/portfolio/assets/content-showcase/science-learning-by-doing.png"
)
FIXTURE_IMAGE_SHA256 = "120295d1743380b584239c385dfd93266d7b30c850c3e98291cd9e3f7a29b9af"
FIXTURE_IMAGE_BYTE_SIZE = 1_392_227
FIXTURE_IMAGE_MEDIA_TYPE = "image/png"
FIXTURE_BODY_IMAGE_RELATIVE_PATHS = (
    Path("docs/portfolio/assets/content-showcase/xiaosai-science-observe-v1.png"),
    Path("docs/portfolio/assets/content-showcase/xiaosai-science-experiment-v1.png"),
    Path("docs/portfolio/assets/content-showcase/xiaosai-science-reflect-v1.png"),
)
FIXTURE_BODY_IMAGE_SHA256S = (
    "3646a4bd12e028519404ddac2e332a5c9d5681383b58a40b89551a9f037d1ca2",
    "408e5338e9c7ca43b7717c43e9e3b2e6eb34d87982dc41209a13f934974d0cda",
    "56d501efe649b41f709c527b47058dd181e807908287a286788fbd540b5e3932",
)
FIXTURE_BODY_IMAGE_BYTE_SIZES = (2_846_089, 2_760_791, 2_673_835)
FIXTURE_BODY_IMAGE_LABELS = ("观察现象", "动手验证", "记录复盘")
FIXTURE_BODY_PUBLICATION_RELATIVE_PATHS = (
    Path("docs/portfolio/assets/content-showcase/xiaosai-science-observe-publication-v2.jpg"),
    Path("docs/portfolio/assets/content-showcase/xiaosai-science-experiment-publication-v2.jpg"),
    Path("docs/portfolio/assets/content-showcase/xiaosai-science-reflect-publication-v2.jpg"),
)
FIXTURE_BODY_PUBLICATION_SHA256S = (
    "dd24dc59546bd712fe61ce4b1e173a095e2cabd43b4cf6f64761ffcd1768cc45",
    "2b37891d5cd9a5c4e3a330e01e9b6fddfc30a5a7da70ba3b8d998cc310228f0c",
    "f2a2bbfe43e0d8905e39a706a6e432f43a3ef88bd80d38164be7d013cced5f1d",
)
FIXTURE_BODY_PUBLICATION_BYTE_SIZES = (287_970, 252_376, 254_978)
FIXTURE_BODY_PUBLICATION_MEDIA_TYPE = "image/jpeg"
FIXTURE_BODY_PUBLICATION_DIMENSIONS = ((1536, 1024),) * 3
FIXTURE_BODY_SEMANTIC_TAGS = (
    ("观察", "现象", "问题", "叶片"),
    ("实验", "验证", "条件", "猜想"),
    ("记录", "复盘", "表达", "修正"),
)
FIXTURE_BODY_ALT_TEXTS = (
    "孩子用放大镜观察叶片，把最初的好奇变成可以描述的问题",
    "孩子和家长一起完成小实验，用一次只改变一个条件来核对猜想",
    "孩子整理观察记录并讲述变化，在复盘中允许自己修正原来的解释",
)
FIXTURE_BODY_CAPTIONS = (
    "从观察叶片细节开始，让问题变得具体。",
    "一次只改变一个条件，帮助孩子核对猜想。",
    "记录结果并允许修改，是探究的重要一步。",
)
FIXTURE_COVER_RELATIVE_PATH = Path(
    "docs/portfolio/assets/content-showcase/xiaosai-science-inquiry-cover-v1.png"
)
FIXTURE_COVER_SHA256 = "9f2ac22535e30dfa03530347420df93121bd2e7b93ed3a67b0c93eb668022a50"
FIXTURE_COVER_BYTE_SIZE = 2_268_247
FIXTURE_COVER_MEDIA_TYPE = "image/png"
FIXTURE_COVER_PUBLICATION_RELATIVE_PATH = Path(
    "docs/portfolio/assets/content-showcase/xiaosai-science-inquiry-cover-publication-v2.jpg"
)
FIXTURE_COVER_PUBLICATION_SHA256 = (
    "3186de546e92409bd7180ffca374aafc2062b7491e1d6bb522ac7b092eef2b4e"
)
FIXTURE_COVER_PUBLICATION_BYTE_SIZE = 209_477
FIXTURE_COVER_PUBLICATION_MEDIA_TYPE = "image/jpeg"
FIXTURE_COVER_PUBLICATION_DIMENSIONS = (1923, 818)


def fixture_image_path() -> Path:
    return Path(__file__).resolve().parents[3] / FIXTURE_IMAGE_RELATIVE_PATH


def fixture_cover_path() -> Path:
    return Path(__file__).resolve().parents[3] / FIXTURE_COVER_RELATIVE_PATH


def fixture_body_image_path(ordinal: int) -> Path:
    if ordinal < 0 or ordinal >= len(FIXTURE_BODY_IMAGE_RELATIVE_PATHS):
        raise ValueError("fixture body image ordinal is outside the approved catalog")
    return Path(__file__).resolve().parents[3] / FIXTURE_BODY_IMAGE_RELATIVE_PATHS[ordinal]


def fixture_body_publication_path(ordinal: int) -> Path:
    if ordinal < 0 or ordinal >= len(FIXTURE_BODY_PUBLICATION_RELATIVE_PATHS):
        raise ValueError("fixture publication body ordinal is outside the approved catalog")
    return Path(__file__).resolve().parents[3] / FIXTURE_BODY_PUBLICATION_RELATIVE_PATHS[ordinal]


def fixture_cover_publication_path() -> Path:
    return Path(__file__).resolve().parents[3] / FIXTURE_COVER_PUBLICATION_RELATIVE_PATH


def fixture_media_path(*, role: str, checksum: str) -> Path:
    if role == "body" and checksum in FIXTURE_BODY_PUBLICATION_SHA256S:
        return fixture_body_publication_path(FIXTURE_BODY_PUBLICATION_SHA256S.index(checksum))
    if role == "body" and checksum in FIXTURE_BODY_IMAGE_SHA256S:
        return fixture_body_image_path(FIXTURE_BODY_IMAGE_SHA256S.index(checksum))
    if role == "body" and checksum == FIXTURE_IMAGE_SHA256:
        return fixture_image_path()
    if role == "cover" and checksum == FIXTURE_COVER_SHA256:
        return fixture_cover_path()
    if role == "cover" and checksum == FIXTURE_COVER_PUBLICATION_SHA256:
        return fixture_cover_publication_path()
    if role == "cover" and checksum == FIXTURE_IMAGE_SHA256:
        return fixture_image_path()
    raise ValueError("fixture media role and checksum are not an approved pairing")


def fixture_source_snapshot(
    *,
    multi_image: bool = False,
    semantic_media: bool = False,
) -> OfficialAccountSourceSnapshot:
    evidence = OfficialAccountEvidence(
        evidence_id=FIXTURE_EVIDENCE_ID,
        source_url="https://example.invalid/sanitized-science-learning",
        source_name=("科学探究过程资料" if semantic_media else "脱敏科学教育示例来源"),
        source_tier=("reference" if semantic_media else "fixture"),
        exact_quote="一次完整的科学探究通常包含观察、提出问题、形成假设、动手验证与复盘表达。",
    )
    brand = OfficialAccountBrandContext(
        brand_chunk_id=FIXTURE_BRAND_CHUNK_ID,
        document_title=("家庭科学探究表达原则" if semantic_media else "脱敏品牌表达示例"),
        text="尊重孩子的好奇心，以可靠事实为起点，用温和、清晰、可行动的方式陪伴家庭探索科学。",
        tone_tags=("温和", "清晰", "启发"),
        safety_tags=("不夸大", "不制造焦虑"),
    )
    source_payload = {
        "fixture_id": OFFICIAL_ACCOUNT_FIXTURE_ID,
        "topic_title": "从一个问题开始，陪孩子完成一次科学探究",
        "topic_summary": (
            "从家庭里的观察、提问、验证和复盘出发，陪孩子走完一次可以完成的科学探究。"
            if semantic_media
            else "用脱敏材料演示如何把可靠信息组织成长文，并保留事实、品牌和观点的边界。"
        ),
        "existing_copy": "科学学习的价值，不只在答案，更在孩子如何观察、提问、验证和表达。",
        "evidence": evidence,
        "brand": brand,
        "fixture_image_sha256": (
            list(FIXTURE_BODY_PUBLICATION_SHA256S)
            if semantic_media
            else list(FIXTURE_BODY_IMAGE_SHA256S)
            if multi_image
            else FIXTURE_IMAGE_SHA256
        ),
    }
    return OfficialAccountSourceSnapshot(
        source_kind="fixture",
        source_id=OFFICIAL_ACCOUNT_FIXTURE_ID,
        source_fingerprint=fingerprint(source_payload),
        topic_title=str(source_payload["topic_title"]),
        topic_summary=str(source_payload["topic_summary"]),
        existing_copy=str(source_payload["existing_copy"]),
        evidence=(evidence,),
        brand_context=(brand,),
        inherited_quality={
            "copy_validation_passed": True,
            "copy_audit_accepted": True,
            "image_validation_passed": True,
            "image_audit_status": "accepted",
            "manual_review_status": "pending",
        },
    )


class DeterministicFakeOfficialAccountArticleGenerator:
    def __init__(self, *, model: str = "official-account-fixture-v1") -> None:
        self._model = model

    async def generate(
        self,
        request: OfficialAccountGenerationRequest,
    ) -> OfficialAccountGenerationResult:
        evidence = request.source.evidence[0]
        brand = request.source.brand_context[0]
        claims = (
            GeneratedArticleClaim(
                id="fact-1",
                text=evidence.exact_quote,
                kind="external_fact",
                evidence_ids=(evidence.evidence_id,),
            ),
            GeneratedArticleClaim(
                id="brand-1",
                text="尊重孩子的好奇心，用可靠事实和温和提问陪伴探索。",
                kind="brand_statement",
                brand_chunk_ids=(brand.brand_chunk_id,),
            ),
            GeneratedArticleClaim(
                id="opinion-1",
                text="一次好的科学学习，应让孩子看见自己如何从疑问走向证据。",
                kind="opinion",
            ),
            GeneratedArticleClaim(
                id="opinion-2",
                text="家长最有价值的支持，往往不是提前给出答案，而是帮助孩子把思路说清楚。",
                kind="opinion",
            ),
        )
        sections = (
            GeneratedArticleSection(
                heading="问题不是起点之前的停顿，而是探究真正开始的地方",
                blocks=(
                    _paragraph(
                        "孩子说出“为什么”的那一刻，学习还没有偏离正轨，反而刚刚进入最值得珍惜的阶段。成年人容易把问题理解成知识缺口，于是急着补上一个标准答案；但对孩子来说，问题更像一扇门：门后可能藏着观察到的差异、还没说清的猜想，也可能藏着对既有解释的不满足。先不急着关门，给孩子一点描述的时间，常常就能听见真正值得追问的线索。",
                        "opinion-1",
                    ),
                    _paragraph(
                        "脱敏示例材料提醒我们，一次完整的科学探究通常包含观察、提出问题、形成假设、动手验证与复盘表达。这并不意味着每次家庭讨论都要变成实验课，而是提示我们：答案只是过程中的一个节点。孩子能否说出自己看见了什么、为什么这样猜、准备怎样验证，比背下一句结论更能显示思考正在发生。",
                        "fact-1",
                    ),
                    _paragraph(
                        "可以从很小的动作开始。把“你怎么还不会”换成“你先看到了什么”，把“正确答案是”换成“还有没有别的解释”。这些问题不会替孩子做决定，却会帮助他们把注意力重新放回现象、证据和推理。问题被认真对待，孩子也更愿意承认不知道、修正猜想，并把一次偶然发现继续发展下去。",
                        "opinion-2",
                    ),
                    _callout(
                        "先保护问题，再讨论答案；先请孩子描述证据，再一起判断解释。",
                        "brand-1",
                    ),
                ),
            ),
            GeneratedArticleSection(
                heading="把观察变成可核对的证据，孩子才拥有自己的判断",
                blocks=(
                    _paragraph(
                        "观察不是“看过了”这么简单。真正可用于讨论的观察，需要尽量具体：发生了什么变化，变化前后有什么不同，在什么条件下出现，是否能够再次看到。家长可以邀请孩子画一张简单记录表，写下时间、条件和结果；年龄较小的孩子也可以用图画、贴纸或口述完成。记录让稍纵即逝的印象变成可以回看的材料，也让争论从“我觉得”转向“我们看到了什么”。",
                        "opinion-1",
                    ),
                    _paragraph(
                        "当孩子的猜想与结果不一致时，不必马上把它判为失败。猜想被证据推翻，恰恰说明验证发挥了作用。可以追问：是哪一个现象让原来的解释站不住了？如果改变一个条件，会不会得到不同结果？这样的复盘会逐渐建立一种朴素但重要的习惯——观点可以坚定表达，也必须愿意接受证据检验。",
                        "opinion-2",
                    ),
                    _paragraph(
                        "可靠事实与品牌表达在这里承担不同任务。事实告诉我们探究过程包含哪些关键环节，品牌表达则提醒我们用怎样的态度陪伴孩子：尊重好奇心，不夸大结果，不用焦虑推动学习。两者不能互相替代。温和语气不能证明事实，可靠来源也不会自动给出适合每个家庭的沟通方式；把边界讲清楚，反而让内容更可信。",
                        "fact-1",
                        "brand-1",
                    ),
                    _callout(
                        "记录的目的不是留下漂亮作业，而是让孩子能够回到证据，解释自己为什么改变了想法。",
                        "opinion-1",
                    ),
                ),
            ),
            GeneratedArticleSection(
                heading="一次可完成的小实验，比一场过度设计的演示更有力量",
                blocks=(
                    _paragraph(
                        "家庭探究不需要昂贵器材。一个透明杯、几张纸、一盏台灯，甚至窗边一天中的光影，都可以成为起点。关键是只改变一个容易识别的条件，并提前说清准备观察什么。孩子如果参与选择材料、安排步骤和预测结果，就不再只是观看成年人完成表演，而是在承担一个真实、可理解的探究任务。",
                        "opinion-1",
                    ),
                    _paragraph(
                        "过程也要允许停顿。孩子可能忘记记录，可能临时改变步骤，也可能因为结果不明显而失去耐心。与其接管，不如帮助他缩小问题：我们能不能先比较两种情况？哪一步最需要重新做？今天只完成观察，明天再解释行不行？把任务拆小并不是降低要求，而是让思考拥有继续发生的条件。",
                        "opinion-2",
                    ),
                    _paragraph(
                        "当结果出现后，可以请孩子用三句话复盘：我原来怎么想，我看到了什么，我现在怎样解释。如果愿意，再加一句“下一次我想改变什么”。这四句话把观察、假设、验证和复盘串在一起，也对应了示例材料中描述的完整探究过程。长期坚持，孩子得到的不是某个实验的标准台词，而是一套能够迁移到新问题上的思考顺序。",
                        "fact-1",
                    ),
                    _callout(
                        "让孩子拥有步骤中的选择权，也拥有根据结果修正想法的权利。",
                        "brand-1",
                    ),
                ),
            ),
            GeneratedArticleSection(
                heading="家长的角色不是答案仓库，而是共同核对思路的伙伴",
                blocks=(
                    _paragraph(
                        "面对孩子的问题，成年人也可以坦然说“不确定，我们一起查一查”。这句话不是示弱，而是在示范如何对待未知。接下来可以共同区分：哪些是刚才亲眼观察到的，哪些来自可靠资料，哪些只是目前的猜想。不同信息被放在不同位置，孩子便能逐渐理解，事实、品牌建议和个人观点各有用途，也各有不能越过的边界。",
                        "opinion-2",
                    ),
                    _paragraph(
                        "陪伴还意味着关注表达，而不仅是结果。请孩子讲给另一个家人听，往往能暴露推理中跳过的环节；请他画出步骤，也可能发现条件没有控制好。表达不是探究完成后的装饰，它本身就是复盘工具。一个能够把证据、猜想和结论分开讲述的孩子，更有可能在面对新信息时保持开放，同时不轻易被确定语气带走。",
                        "opinion-1",
                    ),
                    _paragraph(
                        "尊重好奇心，并不等于对所有说法都点头；温和陪伴，也不等于回避判断。更稳妥的方式是把评价落在过程上：这个记录很清楚，这个猜想还需要证据，这次修改让解释更完整。孩子听见的是具体反馈，而不是对聪明与否的笼统裁决，于是更愿意继续尝试，也更能理解严谨和鼓励可以同时存在。",
                        "brand-1",
                        "opinion-2",
                    ),
                    _callout(
                        "今天不必完成一堂完美的科学课，只要和孩子认真走完一个从问题到证据的小循环。",
                        "brand-1",
                    ),
                ),
            ),
        )
        draft = GeneratedArticleDraft(
            title="从一个“为什么”开始：陪孩子走完科学探究的小循环",
            digest="科学学习不只关乎答案。保护问题、记录观察、验证猜想并复盘表达，能让孩子逐步建立证据意识和独立判断。",
            author=request.identity.default_author,
            lead="当孩子追问“为什么”，我们最容易做的是立刻给出答案。可如果稍微慢一点，就会发现这个问题也许正连接着一次真实的观察、一段尚未成形的推理，以及孩子愿意继续探索的动力。家庭中的科学教育，不一定从复杂设备开始，它可以从认真听完一个问题开始。",
            sections=sections,
            conclusion="科学探究不是少数人的专业姿势，而是一种可以在日常生活里反复练习的思考方式。下一次孩子发问时，不妨先和他一起确认观察、写下猜想、设计一个可完成的小验证，再请他讲讲想法发生了什么变化。当问题被尊重、证据被看见、修正被允许，好奇心就不只是短暂兴奋，而会慢慢成为面对未知时可靠的力量。",
            claims=claims,
        )
        generation_versions = (
            request.identity.generator_prompt_version,
            request.identity.rule_version,
        )
        if generation_versions in {
            (
                OFFICIAL_ACCOUNT_GENERATOR_PROMPT_V4_VERSION,
                OFFICIAL_ACCOUNT_RULE_VERSION,
            ),
            (
                OFFICIAL_ACCOUNT_GENERATOR_PROMPT_V5_VERSION,
                OFFICIAL_ACCOUNT_RULE_VERSION,
            ),
            (
                OFFICIAL_ACCOUNT_GENERATOR_PROMPT_VERSION,
                OFFICIAL_ACCOUNT_RULE_VERSION,
            ),
        }:
            draft = _reader_fixture_draft(draft)
        elif generation_versions == (
            OFFICIAL_ACCOUNT_GENERATOR_PROMPT_V7_VERSION,
            OFFICIAL_ACCOUNT_RULE_VERSION,
        ):
            draft = _five_section_fixture_draft(_reader_fixture_draft(draft))
        elif generation_versions not in {
            (OFFICIAL_ACCOUNT_GENERATOR_PROMPT_V1_VERSION, OFFICIAL_ACCOUNT_RULE_V1_VERSION),
            (OFFICIAL_ACCOUNT_GENERATOR_PROMPT_V2_VERSION, OFFICIAL_ACCOUNT_RULE_V2_VERSION),
            (OFFICIAL_ACCOUNT_GENERATOR_PROMPT_V3_VERSION, OFFICIAL_ACCOUNT_RULE_V3_VERSION),
        }:
            raise ValueError("official-account fixture generator version bundle is unsupported")
        return OfficialAccountGenerationResult(
            draft=draft,
            provider="fake",
            model=self._model,
            request_fingerprint=generation_request_fingerprint(request),
            provider_request_id=None,
            prompt_tokens=0,
            completion_tokens=0,
            reasoning_tokens=0,
            latency_ms=0,
        )


def _reader_fixture_draft(draft: GeneratedArticleDraft) -> GeneratedArticleDraft:
    replacements = {
        (
            "脱敏示例材料提醒我们，一次完整的科学探究通常包含观察、提出问题、形成假设、"
            "动手验证与复盘表达。这并不意味着每次家庭讨论都要变成实验课，而是提示我们："
            "答案只是过程中的一个节点。孩子能否说出自己看见了什么、为什么这样猜、准备怎样验证，"
            "比背下一句结论更能显示思考正在发生。"
        ): (
            "一次完整的科学探究通常包含观察、提出问题、形成假设、动手验证与复盘表达。"
            "这并不意味着每次家庭讨论都要变成实验课，而是提醒我们：答案只是过程中的一个节点。"
            "孩子能否说出自己看见了什么、为什么这样猜、准备怎样验证，比背下一句结论更能显示"
            "思考正在发生。"
        ),
        (
            "可靠事实与品牌表达在这里承担不同任务。事实告诉我们探究过程包含哪些关键环节，"
            "品牌表达则提醒我们用怎样的态度陪伴孩子：尊重好奇心，不夸大结果，不用焦虑推动学习。"
            "两者不能互相替代。温和语气不能证明事实，可靠来源也不会自动给出适合每个家庭的沟通方式；"
            "把边界讲清楚，反而让内容更可信。"
        ): (
            "陪孩子探究时，既要尊重事实，也要留意沟通方式。我们可以保护好奇心，不夸大一次结果，"
            "也不用焦虑催促学习；同时仍要回到观察和可靠资料，核对结论能否成立。温和不等于含糊，"
            "严谨也不必变成压力，把两者放在一起，家庭讨论会更踏实。"
        ),
        (
            "面对孩子的问题，成年人也可以坦然说“不确定，我们一起查一查”。这句话不是示弱，而是在"
            "示范如何对待未知。接下来可以共同区分：哪些是刚才亲眼观察到的，哪些来自可靠资料，哪些"
            "只是目前的猜想。不同信息被放在不同位置，孩子便能逐渐理解，事实、品牌建议和个人观点各有"
            "用途，也各有不能越过的边界。"
        ): (
            "面对孩子的问题，成年人也可以坦然说“不确定，我们一起查一查”。这句话不是示弱，而是在"
            "示范如何对待未知。接下来可以共同区分：哪些是刚才亲眼观察到的，哪些来自可靠资料，哪些"
            "只是目前的猜想。把不同信息放在合适的位置，孩子便会逐渐理解：观察可以复核，资料需要辨别，"
            "猜想则要等待新的证据。"
        ),
    }
    sections: list[GeneratedArticleSection] = []
    for section in draft.sections:
        blocks: list[ArticleParagraphBlock | ArticleBulletListBlock | ArticleQuoteBlock] = []
        for block in section.blocks:
            if isinstance(block, ArticleParagraphBlock) and block.text in replacements:
                blocks.append(block.model_copy(update={"text": replacements[block.text]}))
            else:
                blocks.append(block)
        sections.append(section.model_copy(update={"blocks": tuple(blocks)}))
    return draft.model_copy(update={"sections": tuple(sections)})


def _five_section_fixture_draft(draft: GeneratedArticleDraft) -> GeneratedArticleDraft:
    if len(draft.sections) != 4 or len(draft.sections[-1].blocks) != 4:
        raise ValueError("official-account v7 fixture section shape changed")
    final_section = draft.sections[-1]
    sections = (
        *draft.sections[:-1],
        final_section.model_copy(update={"blocks": final_section.blocks[:2]}),
        GeneratedArticleSection(
            heading="把严谨和鼓励放在一起，让下一次探索自然发生",
            blocks=final_section.blocks[2:],
        ),
    )
    return draft.model_copy(update={"sections": sections})


class DeterministicFakeOfficialAccountArticleAuditor:
    def __init__(self, *, model: str = "official-account-fixture-v1") -> None:
        self._model = model

    async def audit(
        self,
        request: OfficialAccountAuditRequest,
    ) -> OfficialAccountAuditResult:
        return OfficialAccountAuditResult(
            verdict=OfficialAccountAuditVerdict(accepted=True),
            provider="fake",
            model=self._model,
            request_fingerprint=audit_request_fingerprint(request),
            provider_request_id=None,
            prompt_tokens=0,
            completion_tokens=0,
            reasoning_tokens=0,
            latency_ms=0,
        )


class LocalOfficialAccountMediaAdapter:
    def __init__(
        self,
        catalog_media_provider: OfficialAccountCatalogMediaProvider | None = None,
    ) -> None:
        self._catalog_media_provider = catalog_media_provider

    async def stage(
        self,
        request: OfficialAccountMediaRequest,
    ) -> OfficialAccountMediaResult:
        if request.local_adapter_version not in {
            OFFICIAL_ACCOUNT_LOCAL_ADAPTER_V1_VERSION,
            OFFICIAL_ACCOUNT_LOCAL_ADAPTER_V2_VERSION,
            OFFICIAL_ACCOUNT_LOCAL_ADAPTER_V3_VERSION,
            OFFICIAL_ACCOUNT_LOCAL_ADAPTER_V4_VERSION,
            OFFICIAL_ACCOUNT_LOCAL_ADAPTER_VERSION,
            OFFICIAL_ACCOUNT_LOCAL_ADAPTER_V6_VERSION,
            OFFICIAL_ACCOUNT_LOCAL_ADAPTER_V7_VERSION,
        }:
            raise ValueError("official-account local media adapter version is unsupported")
        if request.role == "cover" and request.ordinal != 0:
            raise ValueError("official-account cover media supports ordinal zero only")
        if request.role == "body" and not 0 <= request.ordinal <= 4:
            raise ValueError("official-account body media ordinal is outside zero to four")
        if request.role == "context" and not 0 <= request.ordinal <= 1:
            raise ValueError("official-account context media ordinal is outside zero to one")
        if request.role == "context":
            if (
                request.local_adapter_version
                not in {
                    OFFICIAL_ACCOUNT_LOCAL_ADAPTER_V6_VERSION,
                    OFFICIAL_ACCOUNT_LOCAL_ADAPTER_V7_VERSION,
                }
                or request.source_article_image_id is None
                or request.source_image_artifact_id is not None
                or request.fixture_id is not None
                or request.catalog_asset_id is not None
                or request.catalog_asset_ref is not None
                or request.catalog_version is not None
                or request.source_master_sha256 is not None
                or request.media_type not in {"image/jpeg", "image/png", "image/webp"}
                or request.byte_size <= 0
                or len(request.source_sha256) != 64
            ):
                raise ValueError("source-news context media lineage is invalid")
        elif request.source_article_image_id is not None:
            raise ValueError("source-news media may only use the context role")
        if (
            request.local_adapter_version
            in {
                OFFICIAL_ACCOUNT_LOCAL_ADAPTER_V1_VERSION,
                OFFICIAL_ACCOUNT_LOCAL_ADAPTER_V2_VERSION,
            }
            and request.ordinal != 0
        ):
            raise ValueError("historical official-account adapter supports ordinal zero only")
        local_media_id = f"local-media-{request.role}-{request.request_fingerprint[:24]}"
        media_type = request.media_type
        byte_size = request.byte_size
        checksum = request.source_sha256
        if (
            request.fixture_id is not None
            and request.role == "cover"
            and request.local_adapter_version
            in {
                OFFICIAL_ACCOUNT_LOCAL_ADAPTER_V2_VERSION,
                OFFICIAL_ACCOUNT_LOCAL_ADAPTER_V3_VERSION,
                OFFICIAL_ACCOUNT_LOCAL_ADAPTER_V4_VERSION,
                OFFICIAL_ACCOUNT_LOCAL_ADAPTER_VERSION,
                OFFICIAL_ACCOUNT_LOCAL_ADAPTER_V6_VERSION,
                OFFICIAL_ACCOUNT_LOCAL_ADAPTER_V7_VERSION,
            }
        ):
            if (
                request.fixture_id != OFFICIAL_ACCOUNT_FIXTURE_ID
                or (
                    request.local_adapter_version == OFFICIAL_ACCOUNT_LOCAL_ADAPTER_V2_VERSION
                    and request.source_sha256 != FIXTURE_IMAGE_SHA256
                )
                or (
                    request.local_adapter_version == OFFICIAL_ACCOUNT_LOCAL_ADAPTER_V3_VERSION
                    and request.source_sha256 not in FIXTURE_BODY_IMAGE_SHA256S
                )
                or (
                    request.local_adapter_version == OFFICIAL_ACCOUNT_LOCAL_ADAPTER_V4_VERSION
                    and request.source_sha256 not in FIXTURE_BODY_PUBLICATION_SHA256S
                )
                or (
                    (
                        request.local_adapter_version == OFFICIAL_ACCOUNT_LOCAL_ADAPTER_VERSION
                        or request.local_adapter_version
                        == OFFICIAL_ACCOUNT_LOCAL_ADAPTER_V6_VERSION
                        or request.local_adapter_version
                        == OFFICIAL_ACCOUNT_LOCAL_ADAPTER_V7_VERSION
                    )
                    and (
                        request.source_sha256 != FIXTURE_IMAGE_SHA256
                        or request.media_type != FIXTURE_IMAGE_MEDIA_TYPE
                        or request.byte_size != FIXTURE_IMAGE_BYTE_SIZE
                    )
                )
            ):
                raise ValueError("fixture cover source lineage is invalid")
            if request.local_adapter_version in {
                OFFICIAL_ACCOUNT_LOCAL_ADAPTER_V4_VERSION,
                OFFICIAL_ACCOUNT_LOCAL_ADAPTER_VERSION,
                OFFICIAL_ACCOUNT_LOCAL_ADAPTER_V6_VERSION,
                OFFICIAL_ACCOUNT_LOCAL_ADAPTER_V7_VERSION,
            }:
                media_type = FIXTURE_COVER_PUBLICATION_MEDIA_TYPE
                byte_size = FIXTURE_COVER_PUBLICATION_BYTE_SIZE
                checksum = FIXTURE_COVER_PUBLICATION_SHA256
            else:
                media_type = FIXTURE_COVER_MEDIA_TYPE
                byte_size = FIXTURE_COVER_BYTE_SIZE
                checksum = FIXTURE_COVER_SHA256
        if (
            request.fixture_id is not None
            and request.role == "body"
            and request.local_adapter_version == OFFICIAL_ACCOUNT_LOCAL_ADAPTER_V3_VERSION
        ):
            if (
                request.fixture_id != OFFICIAL_ACCOUNT_FIXTURE_ID
                or request.ordinal >= len(FIXTURE_BODY_IMAGE_SHA256S)
                or request.source_sha256 != FIXTURE_BODY_IMAGE_SHA256S[request.ordinal]
                or request.media_type != FIXTURE_IMAGE_MEDIA_TYPE
                or request.byte_size != FIXTURE_BODY_IMAGE_BYTE_SIZES[request.ordinal]
            ):
                raise ValueError("fixture body source lineage is invalid")
        if (
            request.fixture_id is not None
            and request.role == "body"
            and request.fixture_id == OFFICIAL_ACCOUNT_FIXTURE_ID
            and request.local_adapter_version
            in {
                OFFICIAL_ACCOUNT_LOCAL_ADAPTER_V4_VERSION,
                OFFICIAL_ACCOUNT_LOCAL_ADAPTER_VERSION,
                OFFICIAL_ACCOUNT_LOCAL_ADAPTER_V6_VERSION,
                OFFICIAL_ACCOUNT_LOCAL_ADAPTER_V7_VERSION,
            }
        ):
            catalog_index = (
                FIXTURE_BODY_PUBLICATION_SHA256S.index(request.source_sha256)
                if request.source_sha256 in FIXTURE_BODY_PUBLICATION_SHA256S
                else -1
            )
            if (
                request.fixture_id != OFFICIAL_ACCOUNT_FIXTURE_ID
                or catalog_index < 0
                or request.media_type != FIXTURE_BODY_PUBLICATION_MEDIA_TYPE
                or request.byte_size != FIXTURE_BODY_PUBLICATION_BYTE_SIZES[catalog_index]
            ):
                raise ValueError("fixture publication body source lineage is invalid")
        catalog_lineage = (
            request.catalog_asset_id,
            request.catalog_asset_ref,
            request.catalog_version,
            request.source_master_sha256,
        )
        if any(value is not None for value in catalog_lineage):
            if (
                request.local_adapter_version
                not in {
                    OFFICIAL_ACCOUNT_LOCAL_ADAPTER_VERSION,
                    OFFICIAL_ACCOUNT_LOCAL_ADAPTER_V6_VERSION,
                    OFFICIAL_ACCOUNT_LOCAL_ADAPTER_V7_VERSION,
                }
                or request.role != "body"
                or request.source_image_artifact_id is not None
                or request.catalog_asset_ref is None
                or request.fixture_id != f"catalog:{request.catalog_asset_ref}"
                or request.catalog_asset_id is None
                or len(request.catalog_asset_id) != 64
                or request.source_master_sha256 != request.catalog_asset_id
                or request.catalog_asset_id[:16] != request.catalog_asset_ref
                or request.catalog_version is None
                or request.source_master_sha256 is None
                or request.media_type != "image/jpeg"
                or self._catalog_media_provider is None
            ):
                raise ValueError("catalog publication media lineage is invalid")
            publication = await self._catalog_media_provider.read_publication_bytes(
                catalog_asset_ref=request.catalog_asset_ref,
                catalog_version=request.catalog_version,
                source_master_sha256=request.source_master_sha256,
                publication_sha256=request.source_sha256,
            )
            if len(publication) != request.byte_size:
                raise ValueError("catalog publication media byte size changed")
        return OfficialAccountMediaResult(
            local_media_id=local_media_id,
            role=request.role,
            ordinal=request.ordinal,
            media_url=f"/api/v1/official-account-local/media/{local_media_id}",
            media_type=media_type,
            byte_size=byte_size,
            sha256=checksum,
        )


class LocalOfficialAccountDraftAdapter:
    async def create(
        self,
        request: OfficialAccountDraftRequest,
    ) -> OfficialAccountDraftResult:
        body_media = request.body_media_items or (request.body_media,)
        if request.body_media != body_media[0]:
            raise ValueError("local draft primary body media must be ordinal zero")
        if request.cover_media.role != "cover" or request.cover_media.ordinal != 0:
            raise ValueError("local draft media roles are not interchangeable")
        if tuple(item.ordinal for item in body_media) != tuple(range(len(body_media))):
            raise ValueError("local draft body media must be ordered and contiguous")
        if any(item.role != "body" for item in body_media):
            raise ValueError("local draft media roles are not interchangeable")
        if len({item.sha256 for item in body_media}) != len(body_media):
            raise ValueError("local draft body media checksums must be distinct")
        context_media = request.context_media_items
        if len(context_media) > 2 or tuple(item.ordinal for item in context_media) != tuple(
            range(len(context_media))
        ):
            raise ValueError("local draft context media must be ordered and contiguous")
        if any(
            item.role != "context"
            or item.provenance_kind != "source_news"
            or item.rights_status != "publish_permission_unverified"
            or not item.context_only_not_evidence
            or item.source_page_url is None
            for item in context_media
        ):
            raise ValueError("local draft context media provenance is invalid")
        if len({item.sha256 for item in context_media}) != len(context_media):
            raise ValueError("local draft context media checksums must be distinct")
        return OfficialAccountDraftResult(
            local_draft_id=f"local-draft-{request.request_fingerprint[:24]}",
            simulation=True,
            resolved_html=request.resolved_html,
        )


def _paragraph(text: str, *claim_refs: str) -> ArticleParagraphBlock:
    return ArticleParagraphBlock(kind="paragraph", text=text, claim_refs=claim_refs)


def _callout(text: str, *claim_refs: str) -> ArticleQuoteBlock:
    return ArticleQuoteBlock(kind="callout", text=text, claim_refs=claim_refs)
