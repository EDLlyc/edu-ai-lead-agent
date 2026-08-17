from __future__ import annotations

# ruff: noqa: RUF001
from datetime import UTC, date, datetime
from uuid import UUID

from app.application.ports.agent_workbench import (
    AgentEventMemberRecord,
    AgentEventRecord,
    AgentEvidenceRecord,
    CopyValidationContext,
)
from app.core.errors import NotFoundError
from app.domain.brand_knowledge import BrandAudience, BrandDocumentKind, BrandRetrievalHit
from app.domain.copy_generation import (
    ActiveBrandContext,
    EligibleEvidence,
    LegacyDailyTopicOrigin,
    LockedTopicContext,
)
from app.schemas.copy_generation import (
    DraftClaim,
    MaterialDraft,
    append_copy_news_source_footer,
)

FIXTURE_EVENT_ID = UUID("10000000-0000-4000-8000-000000000001")
FIXTURE_EVENT_VERSION_ID = UUID("10000000-0000-4000-8000-000000000002")
FIXTURE_EVIDENCE_ID = UUID("10000000-0000-4000-8000-000000000003")
FIXTURE_CANDIDATE_ID = UUID("10000000-0000-4000-8000-000000000004")
FIXTURE_PASSAGE_ID = UUID("10000000-0000-4000-8000-000000000005")
FIXTURE_OCCURRENCE_ID = UUID("10000000-0000-4000-8000-000000000006")
FIXTURE_SNAPSHOT_ID = UUID("10000000-0000-4000-8000-000000000007")
FIXTURE_SOURCE_ID = UUID("10000000-0000-4000-8000-000000000008")
FIXTURE_BRAND_CHUNK_ID = UUID("20000000-0000-4000-8000-000000000001")
FIXTURE_BRAND_DOCUMENT_ID = UUID("20000000-0000-4000-8000-000000000002")
FIXTURE_BRAND_VERSION_ID = UUID("20000000-0000-4000-8000-000000000003")
FIXTURE_COPY_RUN_ID = UUID("30000000-0000-4000-8000-000000000001")
FIXTURE_TOPIC_SELECTION_ID = UUID("30000000-0000-4000-8000-000000000002")
FIXTURE_TOPIC_SELECTION_RUN_ID = UUID("30000000-0000-4000-8000-000000000003")

FIXTURE_SCENARIOS = frozenset(
    {"evidence", "event", "brand", "copy_validation", "multi_tool", "insufficient"}
)
_EVIDENCE_TITLE = "教育部门发布人工智能教育应用指导意见"
_EVIDENCE_QUOTE = "指导意见提出，学校应在安全、透明和教师监督下开展人工智能教育应用。"
_EVIDENCE_URL = "https://example.edu.cn/policy/ai-education-guidance"


class FixtureAgentKnowledgeReader:
    """Sanitized, deterministic, provider-free workbench data adapter."""

    def __init__(self, *, scenario_id: str | None = None) -> None:
        if scenario_id is not None and scenario_id not in FIXTURE_SCENARIOS:
            raise ValueError("unknown agent workbench fixture scenario")
        self._scenario_id = scenario_id
        evidence = EligibleEvidence(
            evidence_id=FIXTURE_EVIDENCE_ID,
            candidate_id=FIXTURE_CANDIDATE_ID,
            passage_id=FIXTURE_PASSAGE_ID,
            occurrence_id=FIXTURE_OCCURRENCE_ID,
            snapshot_id=FIXTURE_SNAPSHOT_ID,
            source_name="示例教育部门",
            source_url=_EVIDENCE_URL,
            source_tier="A",
            published_at=datetime(2026, 8, 12, 2, 0, tzinfo=UTC),
            exact_quote=_EVIDENCE_QUOTE,
            governed_statement="学校开展人工智能教育应用时应保留安全、透明和教师监督。",
        )
        self._evidence = AgentEvidenceRecord(
            evidence=evidence,
            event_id=FIXTURE_EVENT_ID,
            event_version_id=FIXTURE_EVENT_VERSION_ID,
            source_id=FIXTURE_SOURCE_ID,
            event_title=_EVIDENCE_TITLE,
        )
        self._brand_hit = BrandRetrievalHit(
            chunk_id=FIXTURE_BRAND_CHUNK_ID,
            document_id=FIXTURE_BRAND_DOCUMENT_ID,
            version_id=FIXTURE_BRAND_VERSION_ID,
            document_title="赛先生家长沟通原则（脱敏示例）",
            document_kind=BrandDocumentKind.TONE,
            audience=BrandAudience.PARENTS,
            text="用清楚、克制的语言连接科学事实与孩子的观察、提问和实践，不承诺升学结果。",
            tone_tags=("清楚", "克制", "启发式"),
            safety_tags=("不承诺结果",),
            visual_tags=(),
            full_text_score=1.0,
            vector_score=1.0,
            fused_score=1.0,
        )

    async def search_evidence(
        self,
        *,
        query: str,
        limit: int,
        candidate_id: UUID | None,
    ) -> tuple[AgentEvidenceRecord, ...]:
        if self._scenario_id == "insufficient" or _fixture_query_is_insufficient(query):
            return ()
        if candidate_id is not None and candidate_id != FIXTURE_CANDIDATE_ID:
            return ()
        return (self._evidence,)[:limit]

    async def get_event(self, event_id: UUID) -> AgentEventRecord:
        if event_id != FIXTURE_EVENT_ID:
            raise NotFoundError("event")
        return AgentEventRecord(
            event_id=FIXTURE_EVENT_ID,
            current_version_id=FIXTURE_EVENT_VERSION_ID,
            representative_title=_EVIDENCE_TITLE,
            summary="该事件聚合了人工智能教育应用中的安全、透明和教师监督要求。",
            source_diversity=1,
            categories=("education_policy", "ai_education"),
            members=(
                AgentEventMemberRecord(
                    candidate_id=FIXTURE_CANDIDATE_ID,
                    title=_EVIDENCE_TITLE,
                    url=_EVIDENCE_URL,
                    published_at=self._evidence.evidence.published_at,
                    source_ids=(FIXTURE_SOURCE_ID,),
                    source_names=("示例教育部门",),
                ),
            ),
        )

    async def retrieve_brand_context(
        self,
        *,
        query: str,
        audience: BrandAudience,
        document_kinds: tuple[BrandDocumentKind, ...],
        valid_on: date,
        limit: int,
    ) -> tuple[BrandRetrievalHit, ...]:
        del query, valid_on
        if self._scenario_id == "insufficient" or audience is not BrandAudience.PARENTS:
            return ()
        if document_kinds and self._brand_hit.document_kind not in document_kinds:
            return ()
        return (self._brand_hit,)[:limit]

    async def load_copy_validation_context(
        self,
        *,
        copy_run_id: UUID,
        brand_chunk_ids: tuple[UUID, ...],
    ) -> CopyValidationContext:
        if copy_run_id != FIXTURE_COPY_RUN_ID:
            raise NotFoundError("copy generation run")
        if any(chunk_id != FIXTURE_BRAND_CHUNK_ID for chunk_id in brand_chunk_ids):
            raise NotFoundError("brand chunk")
        brand_context = (
            (
                ActiveBrandContext(
                    chunk_id=self._brand_hit.chunk_id,
                    document_id=self._brand_hit.document_id,
                    version_id=self._brand_hit.version_id,
                    document_title=self._brand_hit.document_title,
                    document_kind=self._brand_hit.document_kind.value,
                    text=self._brand_hit.text,
                    tone_tags=self._brand_hit.tone_tags,
                    safety_tags=self._brand_hit.safety_tags,
                    visual_tags=self._brand_hit.visual_tags,
                ),
            )
            if brand_chunk_ids
            else ()
        )
        return CopyValidationContext(
            copy_run_id=copy_run_id,
            topic=LockedTopicContext(
                origin=LegacyDailyTopicOrigin(
                    daily_topic_selection_id=FIXTURE_TOPIC_SELECTION_ID,
                    topic_selection_run_id=FIXTURE_TOPIC_SELECTION_RUN_ID,
                ),
                business_date=date(2026, 8, 16),
                timezone="Asia/Shanghai",
                scoring_profile="preview",
                decision_kind="selected",
                selected_event_id=FIXTURE_EVENT_ID,
                selected_event_version_id=FIXTURE_EVENT_VERSION_ID,
                no_topic_code=None,
                title=_EVIDENCE_TITLE,
                summary="学校应在安全、透明和教师监督下开展人工智能教育应用。",
                evidence=(self._evidence.evidence,),
            ),
            brand_context=brand_context,
            rule_version="preview-v11-compact-content-warning-recovery",
        )


def build_fixture_reader(scenario_id: str | None = None) -> FixtureAgentKnowledgeReader:
    return FixtureAgentKnowledgeReader(scenario_id=scenario_id)


def build_fixture_material_draft() -> MaterialDraft:
    fact = _EVIDENCE_QUOTE
    brand = "赛先生重视孩子在真实问题中的观察、提问和实践。"
    opinion = "家长可以从一起核对信息来源开始，陪孩子形成审慎使用人工智能的习惯。"
    body = f"小赛洞察：{fact}📰\n{opinion}🔍\n\n{brand}🌱"
    copywriting = append_copy_news_source_footer(
        f"{body}\n#赛先生科学 #人工智能教育 #科学思维",
        source_name="示例教育部门",
        source_url=_EVIDENCE_URL,
    )
    return MaterialDraft(
        copywriting=copywriting,
        parent_takeaway="和孩子一起核对来源、讨论边界，比追逐工具热度更重要。",
        interaction="你会先和孩子讨论人工智能的哪一条使用边界？",
        source_note=f"信息来源：示例教育部门，{_EVIDENCE_URL}",
        image_prompt="友好克制的科学教育插画，家长和孩子共同核对信息来源，不含宣传承诺。",
        claims=(
            DraftClaim(
                id="fact-1",
                text=fact,
                kind="external_fact",
                evidence_ids=(FIXTURE_EVIDENCE_ID,),
            ),
            DraftClaim(
                id="brand-1",
                text=brand,
                kind="brand_statement",
                brand_chunk_ids=(FIXTURE_BRAND_CHUNK_ID,),
            ),
            DraftClaim(id="opinion-1", text=opinion, kind="opinion"),
        ),
    )


def _fixture_query_is_insufficient(query: str) -> bool:
    normalized = query.casefold()
    return any(
        marker in normalized
        for marker in ("不存在", "insufficient", "量子香蕉", "火星小学", "没有证据")
    )
