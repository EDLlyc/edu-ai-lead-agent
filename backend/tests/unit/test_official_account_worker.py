from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from hashlib import sha256
from io import BytesIO
from uuid import UUID, uuid4

import pytest
from app.application.ports.image_generation import ImageGenerationRequest
from app.application.ports.official_account_local import (
    ClaimedOfficialAccountRun,
    OfficialAccountAuditResult,
    OfficialAccountDraftResult,
    OfficialAccountGeneratedVisualPlan,
    OfficialAccountGeneratedVisualResult,
    OfficialAccountGenerationResult,
    OfficialAccountMediaResult,
    OfficialAccountMediaSemanticRanker,
    OfficialAccountSourceMedia,
    OfficialAccountVersionIdentity,
    StoredOfficialAccountArticle,
    StoredOfficialAccountGeneratedVisual,
    StoredOfficialAccountRender,
)
from app.application.services import official_account_local as official_account_service
from app.application.services.official_account_local import OfficialAccountLocalExecutor
from app.core.config import Settings
from app.core.errors import ImageProviderTimeoutError, LocalDraftResultUnknownError
from app.domain.official_account_local import (
    OFFICIAL_ACCOUNT_ARTICLE_SCHEMA_VERSION,
    OFFICIAL_ACCOUNT_AUDITOR_PROMPT_VERSION,
    OFFICIAL_ACCOUNT_GENERATED_VISUAL_PLAN_VERSION,
    OFFICIAL_ACCOUNT_GENERATED_VISUAL_PROMPT_VERSION,
    OFFICIAL_ACCOUNT_GENERATOR_PROMPT_VERSION,
    OFFICIAL_ACCOUNT_LOCAL_ADAPTER_V2_VERSION,
    OFFICIAL_ACCOUNT_LOCAL_ADAPTER_VERSION,
    OFFICIAL_ACCOUNT_MEDIA_PLAN_VERSION,
    OFFICIAL_ACCOUNT_RENDERER_VERSION,
    OFFICIAL_ACCOUNT_RULE_VERSION,
    OFFICIAL_ACCOUNT_STYLE_VERSION,
    OFFICIAL_ACCOUNT_TEMPLATE_VERSION,
    OFFICIAL_ACCOUNT_VISUAL_QUERY_VERSION,
    OFFICIAL_ACCOUNT_VISUAL_SELECTOR_VERSION,
    ArticlePackage,
    ArticleValidationIssue,
    OfficialAccountAuditVerdict,
    RenderedOfficialAccountHtml,
)
from app.domain.official_account_local import (
    render_wechat_html as render_wechat_html_domain,
)
from app.infrastructure.ai.image_generation import DeterministicFakeImageGenerator
from app.infrastructure.official_account_local import (
    FIXTURE_BODY_ALT_TEXTS,
    FIXTURE_BODY_CAPTIONS,
    FIXTURE_BODY_IMAGE_LABELS,
    FIXTURE_BODY_IMAGE_SHA256S,
    FIXTURE_BODY_PUBLICATION_BYTE_SIZES,
    FIXTURE_BODY_PUBLICATION_MEDIA_TYPE,
    FIXTURE_BODY_PUBLICATION_SHA256S,
    FIXTURE_BODY_SEMANTIC_TAGS,
    FIXTURE_IMAGE_BYTE_SIZE,
    FIXTURE_IMAGE_MEDIA_TYPE,
    FIXTURE_IMAGE_SHA256,
    DeterministicFakeOfficialAccountArticleAuditor,
    DeterministicFakeOfficialAccountArticleGenerator,
    LocalOfficialAccountDraftAdapter,
    LocalOfficialAccountMediaAdapter,
    fixture_source_snapshot,
)
from app.official_account_local_cli import _identity as cli_identity
from PIL import Image


def _identity() -> OfficialAccountVersionIdentity:
    return OfficialAccountVersionIdentity(
        provider="fake",
        model="official-account-fixture-v1",
        generator_prompt_version="official-account-generator-v1",
        article_schema_version="official-account-article-schema-v1",
        auditor_prompt_version="official-account-auditor-v1",
        audit_schema_version="official-account-audit-schema-v1",
        rule_version="official-account-rules-v1",
        renderer_version="wechat-html-renderer-v1",
        style_version="wechat-inline-style-v1",
        template_version="wechat-fragment-template-v1",
        local_adapter_version=OFFICIAL_ACCOUNT_LOCAL_ADAPTER_V2_VERSION,
        default_author="赛先生",
        min_characters=1_200,
        target_min_characters=1_800,
        target_max_characters=2_600,
        max_characters=4_000,
    )


def _current_identity() -> OfficialAccountVersionIdentity:
    historical = _identity()
    return OfficialAccountVersionIdentity(
        provider=historical.provider,
        model=historical.model,
        generator_prompt_version=OFFICIAL_ACCOUNT_GENERATOR_PROMPT_VERSION,
        article_schema_version=OFFICIAL_ACCOUNT_ARTICLE_SCHEMA_VERSION,
        auditor_prompt_version=OFFICIAL_ACCOUNT_AUDITOR_PROMPT_VERSION,
        audit_schema_version=historical.audit_schema_version,
        rule_version=OFFICIAL_ACCOUNT_RULE_VERSION,
        renderer_version=OFFICIAL_ACCOUNT_RENDERER_VERSION,
        style_version=OFFICIAL_ACCOUNT_STYLE_VERSION,
        template_version=OFFICIAL_ACCOUNT_TEMPLATE_VERSION,
        local_adapter_version=OFFICIAL_ACCOUNT_LOCAL_ADAPTER_VERSION,
        default_author=historical.default_author,
        min_characters=historical.min_characters,
        target_min_characters=historical.target_min_characters,
        target_max_characters=historical.target_max_characters,
        max_characters=historical.max_characters,
        media_plan_version=OFFICIAL_ACCOUNT_MEDIA_PLAN_VERSION,
        visual_query_version=OFFICIAL_ACCOUNT_VISUAL_QUERY_VERSION,
        visual_selector_version=OFFICIAL_ACCOUNT_VISUAL_SELECTOR_VERSION,
    )


@pytest.mark.parametrize(
    "field_name",
    (
        "official_account_local_generator_prompt_version",
        "official_account_local_article_schema_version",
        "official_account_local_media_plan_version",
        "official_account_local_auditor_prompt_version",
        "official_account_local_audit_schema_version",
        "official_account_local_rule_version",
        "official_account_local_renderer_version",
        "official_account_local_style_version",
        "official_account_local_template_version",
        "official_account_local_adapter_version",
        "official_account_local_visual_query_version",
        "official_account_local_visual_selector_version",
    ),
)
def test_settings_reject_each_unknown_or_mixed_current_version(field_name: str) -> None:
    with pytest.raises(ValueError, match="current version bundle is unsupported"):
        Settings(
            _env_file=None,
            official_account_local_enabled=True,
            **{field_name: "unknown-version"},
        )


def test_settings_allow_a_historical_official_account_bundle_while_disabled() -> None:
    settings = Settings(
        _env_file=None,
        official_account_local_generator_prompt_version="official-account-generator-v4-reader-copy",
        official_account_local_auditor_prompt_version="official-account-auditor-v1",
    )

    assert settings.official_account_local_enabled is False


def test_cli_identity_carries_the_complete_current_visual_version_bundle() -> None:
    settings = Settings(_env_file=None)

    identity = cli_identity(
        settings,
        provider="fake",
        model="official-account-fixture-v1",
    )

    assert identity.media_plan_version == OFFICIAL_ACCOUNT_MEDIA_PLAN_VERSION
    assert identity.visual_query_version == OFFICIAL_ACCOUNT_VISUAL_QUERY_VERSION
    assert identity.visual_selector_version == OFFICIAL_ACCOUNT_VISUAL_SELECTOR_VERSION


class _MemoryRepository:
    def __init__(
        self,
        *,
        identity: OfficialAccountVersionIdentity | None = None,
        pause_before_body_ordinal: int | None = None,
    ) -> None:
        self.run_id = uuid4()
        self.identity = identity or _identity()
        self.pause_before_body_ordinal = pause_before_body_ordinal
        self.claimed = False
        self.article: StoredOfficialAccountArticle | None = None
        self.render: StoredOfficialAccountRender | None = None
        self.media: dict[tuple[str, int], tuple[UUID, OfficialAccountMediaResult]] = {}
        self.media_persist_count: dict[tuple[str, int], int] = {}
        self.draft: OfficialAccountDraftResult | None = None
        self.failure: tuple[str, bool] | None = None
        self.failure_retryable: bool | None = None
        self.heartbeat_count = 0

    async def claim(
        self,
        *,
        worker_id: str,
        lease_seconds: int,
        max_attempts: int,
    ) -> ClaimedOfficialAccountRun | None:
        del worker_id, lease_seconds, max_attempts
        if self.claimed:
            return None
        self.claimed = True
        return ClaimedOfficialAccountRun(
            run_id=self.run_id,
            attempt_number=1,
            lease_token=uuid4(),
            generation_mode="fixture",
            identity=self.identity,
            current_stage="generating",
        )

    async def heartbeat(
        self,
        *,
        claimed: ClaimedOfficialAccountRun,
        lease_seconds: int,
    ) -> bool:
        del claimed, lease_seconds
        self.heartbeat_count += 1
        return True

    async def load_source(self, claimed: ClaimedOfficialAccountRun):
        del claimed
        return fixture_source_snapshot(
            multi_image=self.identity.media_plan_version == OFFICIAL_ACCOUNT_MEDIA_PLAN_VERSION,
            semantic_media=self.identity.media_plan_version == OFFICIAL_ACCOUNT_MEDIA_PLAN_VERSION,
        )

    async def load_source_media(
        self,
        claimed: ClaimedOfficialAccountRun,
    ) -> OfficialAccountSourceMedia:
        del claimed
        return OfficialAccountSourceMedia(
            source_image_artifact_id=None,
            fixture_id="official-account-article-v1",
            media_type=FIXTURE_IMAGE_MEDIA_TYPE,
            byte_size=FIXTURE_IMAGE_BYTE_SIZE,
            sha256=FIXTURE_IMAGE_SHA256,
        )

    async def load_source_media_candidates(
        self,
        claimed: ClaimedOfficialAccountRun,
    ) -> tuple[OfficialAccountSourceMedia, ...]:
        del claimed
        return tuple(
            OfficialAccountSourceMedia(
                source_image_artifact_id=None,
                fixture_id="official-account-article-v1",
                media_type=FIXTURE_BODY_PUBLICATION_MEDIA_TYPE,
                byte_size=byte_size,
                sha256=checksum,
                ordinal=ordinal,
                candidate_id=checksum[:16],
                semantic_label=FIXTURE_BODY_IMAGE_LABELS[ordinal],
                semantic_tags=FIXTURE_BODY_SEMANTIC_TAGS[ordinal],
                alt_text=FIXTURE_BODY_ALT_TEXTS[ordinal],
                caption_text=FIXTURE_BODY_CAPTIONS[ordinal],
                publication_priority=ordinal,
                selection_reason="本地语义配图候选",
                catalog_version="official-account-fixture-catalog-v1",
                source_master_sha256=FIXTURE_BODY_IMAGE_SHA256S[ordinal],
            )
            for ordinal, (checksum, byte_size) in enumerate(
                zip(
                    FIXTURE_BODY_PUBLICATION_SHA256S,
                    FIXTURE_BODY_PUBLICATION_BYTE_SIZES,
                    strict=True,
                )
            )
        )

    async def get_article(self, run_id: UUID) -> StoredOfficialAccountArticle | None:
        assert run_id == self.run_id
        return self.article

    async def get_render(self, run_id: UUID) -> StoredOfficialAccountRender | None:
        assert run_id == self.run_id
        return self.render

    async def get_media(
        self,
        run_id: UUID,
        role: str,
        ordinal: int = 0,
    ) -> tuple[UUID, OfficialAccountMediaResult] | None:
        assert run_id == self.run_id
        return self.media.get((role, ordinal))

    async def list_media(
        self,
        run_id: UUID,
        role: str | None = None,
    ) -> tuple[tuple[UUID, OfficialAccountMediaResult], ...]:
        assert run_id == self.run_id
        return tuple(
            item
            for (stored_role, _ordinal), item in sorted(self.media.items())
            if role is None or stored_role == role
        )

    async def get_draft(self, run_id: UUID) -> OfficialAccountDraftResult | None:
        assert run_id == self.run_id
        return self.draft

    async def persist_article(
        self,
        *,
        claimed: ClaimedOfficialAccountRun,
        article: ArticlePackage,
        result: OfficialAccountGenerationResult,
        validation_issues: tuple[ArticleValidationIssue, ...],
    ) -> StoredOfficialAccountArticle:
        assert claimed.run_id == self.run_id
        self.article = StoredOfficialAccountArticle(
            id=uuid4(),
            article=article,
            validation_issues=validation_issues,
            audit=None,
            provider_request_id=result.provider_request_id,
            prompt_tokens=result.prompt_tokens,
            completion_tokens=result.completion_tokens,
            reasoning_tokens=result.reasoning_tokens,
            latency_ms=result.latency_ms,
            created_at=datetime.now(UTC),
        )
        return self.article

    async def persist_audit(
        self,
        *,
        claimed: ClaimedOfficialAccountRun,
        article: StoredOfficialAccountArticle,
        result: OfficialAccountAuditResult,
    ) -> StoredOfficialAccountArticle:
        assert claimed.run_id == self.run_id
        self.article = StoredOfficialAccountArticle(
            id=article.id,
            article=article.article,
            validation_issues=article.validation_issues,
            audit=result.verdict,
            provider_request_id=article.provider_request_id,
            prompt_tokens=article.prompt_tokens,
            completion_tokens=article.completion_tokens,
            reasoning_tokens=article.reasoning_tokens,
            latency_ms=article.latency_ms,
            created_at=article.created_at,
        )
        return self.article

    async def persist_render(
        self,
        *,
        claimed: ClaimedOfficialAccountRun,
        article: StoredOfficialAccountArticle,
        rendered: RenderedOfficialAccountHtml,
    ) -> StoredOfficialAccountRender:
        assert claimed.run_id == self.run_id
        self.render = StoredOfficialAccountRender(
            id=uuid4(),
            article_version_id=article.id,
            canonical_html=rendered.canonical_html,
            render_fingerprint=rendered.render_fingerprint,
        )
        return self.render

    async def persist_media(
        self,
        *,
        claimed: ClaimedOfficialAccountRun,
        render: StoredOfficialAccountRender,
        source_media: OfficialAccountSourceMedia,
        request_fingerprint: str,
        result: OfficialAccountMediaResult,
    ) -> tuple[UUID, OfficialAccountMediaResult]:
        del render, source_media, request_fingerprint
        assert claimed.run_id == self.run_id
        key = (result.role, result.ordinal)
        if self.pause_before_body_ordinal == result.ordinal and result.role == "body":
            self.pause_before_body_ordinal = None
            return None
        stored = (uuid4(), result)
        self.media[key] = stored
        self.media_persist_count[key] = self.media_persist_count.get(key, 0) + 1
        return stored

    async def persist_draft(
        self,
        *,
        claimed: ClaimedOfficialAccountRun,
        render: StoredOfficialAccountRender,
        body_media_id: UUID,
        body_media_ids: tuple[UUID, ...],
        cover_media_id: UUID,
        request_fingerprint: str,
        result: OfficialAccountDraftResult,
    ) -> OfficialAccountDraftResult:
        del render, request_fingerprint
        assert claimed.run_id == self.run_id
        assert body_media_id != cover_media_id
        assert body_media_ids
        assert body_media_ids[0] == body_media_id
        self.draft = result
        return result

    async def fail(
        self,
        *,
        claimed: ClaimedOfficialAccountRun,
        error_code: str,
        retryable: bool,
        retry_base_seconds: int,
        max_attempts: int,
        result_unknown: bool = False,
        safe_metadata: dict[str, object] | None = None,
    ) -> bool:
        del claimed, retry_base_seconds, max_attempts, safe_metadata
        self.failure = (error_code, result_unknown)
        self.failure_retryable = retryable
        return True


def _executor(
    repository: _MemoryRepository,
    *,
    draft_adapter: LocalOfficialAccountDraftAdapter | None = None,
    media_semantic_ranker: OfficialAccountMediaSemanticRanker | None = None,
) -> OfficialAccountLocalExecutor:
    return OfficialAccountLocalExecutor(
        repository=repository,
        fixture_generator=DeterministicFakeOfficialAccountArticleGenerator(),
        fixture_auditor=DeterministicFakeOfficialAccountArticleAuditor(),
        live_generator=None,
        live_auditor=None,
        media_adapter=LocalOfficialAccountMediaAdapter(),
        draft_adapter=draft_adapter or LocalOfficialAccountDraftAdapter(),
        lease_seconds=60,
        heartbeat_seconds=10,
        max_attempts=3,
        retry_base_seconds=1,
        generation_max_output_tokens=8_192,
        audit_max_output_tokens=1_024,
        media_semantic_ranker=media_semantic_ranker,
    )


class _CountingSemanticRanker:
    def __init__(self) -> None:
        self.calls = 0

    async def select(self, *, topic_title, sections, candidates, enabled):
        del topic_title, enabled
        self.calls += 1
        return official_account_service._fallback_v7_selection(
            sections=sections,
            candidates=candidates,
            reason="disabled",
        )


class _GeneratedVisualRepository(_MemoryRepository):
    """In-memory durable intent ledger for the worker's opt-in visual path."""

    def __init__(self) -> None:
        super().__init__(
            identity=replace(
                _current_identity(),
                generated_visual_plan_version=OFFICIAL_ACCOUNT_GENERATED_VISUAL_PLAN_VERSION,
                generated_visual_prompt_version=OFFICIAL_ACCOUNT_GENERATED_VISUAL_PROMPT_VERSION,
            )
        )
        self.generated: dict[int, StoredOfficialAccountGeneratedVisual] = {}

    async def claim(
        self,
        *,
        worker_id: str,
        lease_seconds: int,
        max_attempts: int,
    ) -> ClaimedOfficialAccountRun | None:
        claimed = await super().claim(
            worker_id=worker_id,
            lease_seconds=lease_seconds,
            max_attempts=max_attempts,
        )
        return replace(claimed, generation_mode="live") if claimed is not None else None

    async def get_generated_visual(
        self,
        *,
        run_id: UUID,
        ordinal: int,
    ) -> StoredOfficialAccountGeneratedVisual | None:
        assert run_id == self.run_id
        return self.generated.get(ordinal)

    async def create_generated_visual_intent(
        self,
        *,
        claimed: ClaimedOfficialAccountRun,
        plan: OfficialAccountGeneratedVisualPlan,
    ) -> StoredOfficialAccountGeneratedVisual:
        assert claimed.run_id == self.run_id
        existing = self.generated.get(plan.ordinal)
        if existing is not None:
            assert existing.plan == plan
            return existing
        stored = StoredOfficialAccountGeneratedVisual(
            id=uuid4(),
            plan=plan,
            status="generating",
            media_type=None,
            byte_size=None,
            sha256=None,
            width=None,
            height=None,
            error_code=None,
            created_at=datetime.now(UTC),
            completed_at=None,
        )
        self.generated[plan.ordinal] = stored
        return stored

    async def persist_generated_visual(
        self,
        *,
        claimed: ClaimedOfficialAccountRun,
        plan: OfficialAccountGeneratedVisualPlan,
        result: OfficialAccountGeneratedVisualResult,
    ) -> StoredOfficialAccountGeneratedVisual:
        assert claimed.run_id == self.run_id
        current = self.generated[plan.ordinal]
        assert current.plan == plan
        stored = replace(
            current,
            status="ready",
            media_type=result.media_type,
            byte_size=result.byte_size,
            sha256=result.sha256,
            width=result.width,
            height=result.height,
            completed_at=datetime.now(UTC),
        )
        self.generated[plan.ordinal] = stored
        return stored

    async def fail_generated_visual(
        self,
        *,
        claimed: ClaimedOfficialAccountRun,
        plan: OfficialAccountGeneratedVisualPlan,
        error_code: str,
        result_unknown: bool = False,
    ) -> bool:
        assert claimed.run_id == self.run_id
        current = self.generated[plan.ordinal]
        self.generated[plan.ordinal] = replace(
            current,
            status="result_unknown" if result_unknown else "failed",
            error_code=error_code,
            completed_at=datetime.now(UTC),
        )
        return True


class _ApprovedCatalog:
    def __init__(self) -> None:
        self.candidates = tuple(self._candidate(ordinal) for ordinal in range(41))
        self.reference_reads = 0

    @staticmethod
    def _reference_body(ordinal: int) -> bytes:
        output = BytesIO()
        Image.new(
            "RGB",
            (1_536, 1_024),
            ((ordinal * 29) % 255, 93, 151),
        ).save(
            output,
            format="JPEG",
            quality=82,
            optimize=False,
            progressive=False,
            exif=b"",
        )
        return output.getvalue()

    @classmethod
    def _candidate(cls, ordinal: int) -> OfficialAccountSourceMedia:
        reference = f"{ordinal + 1:016x}"
        source_checksum = sha256(f"source:{ordinal}".encode()).hexdigest()
        publication = cls._reference_body(ordinal)
        publication_checksum = sha256(publication).hexdigest()
        return OfficialAccountSourceMedia(
            source_image_artifact_id=None,
            fixture_id=f"catalog:{reference}",
            media_type="image/jpeg",
            byte_size=len(publication),
            sha256=publication_checksum,
            ordinal=ordinal,
            candidate_id=reference,
            semantic_label="批准的小赛 IP 参考素材",
            semantic_tags=("观察", "实验", "记录"),
            alt_text="小赛陪伴孩子观察、实验和记录科学发现",
            caption_text="把观察、验证和记录连成一次完整的小探究。",
            selection_reason="批准目录候选",
            catalog_asset_id=source_checksum,
            catalog_asset_ref=reference,
            catalog_version="brand-visual-catalog-v1",
            source_master_sha256=source_checksum,
        )

    async def load_candidates(self) -> tuple[OfficialAccountSourceMedia, ...]:
        return self.candidates

    async def revalidate_candidate(
        self,
        candidate: OfficialAccountSourceMedia,
    ) -> OfficialAccountSourceMedia:
        refreshed = next(
            item
            for item in self.candidates
            if item.catalog_asset_ref == candidate.catalog_asset_ref
        )
        assert refreshed.sha256 == candidate.sha256
        assert refreshed.source_master_sha256 == candidate.source_master_sha256
        return replace(
            refreshed,
            ordinal=candidate.ordinal,
            assigned_section_index=candidate.assigned_section_index,
            selection_method=candidate.selection_method,
            similarity_band=candidate.similarity_band,
        )

    async def catalog_is_current(
        self,
        candidates: tuple[OfficialAccountSourceMedia, ...],
    ) -> bool:
        return candidates == self.candidates

    async def read_publication_bytes(
        self,
        *,
        catalog_asset_ref: str,
        catalog_version: str,
        source_master_sha256: str,
        publication_sha256: str,
    ) -> bytes:
        assert catalog_version == "brand-visual-catalog-v1"
        candidate = next(
            item for item in self.candidates if item.catalog_asset_ref == catalog_asset_ref
        )
        assert candidate.source_master_sha256 == source_master_sha256
        assert candidate.sha256 == publication_sha256
        self.reference_reads += 1
        return self._reference_body(int(catalog_asset_ref, 16) - 1)


class _CountingFakeImageGenerator(DeterministicFakeImageGenerator):
    def __init__(self) -> None:
        super().__init__(model="gpt-image-2")
        self.requests: list[ImageGenerationRequest] = []

    async def generate(self, request: ImageGenerationRequest):
        self.requests.append(request)
        return await super().generate(request)


class _TimeoutImageGenerator(_CountingFakeImageGenerator):
    async def generate(self, request: ImageGenerationRequest):
        self.requests.append(request)
        raise ImageProviderTimeoutError()


class _MemoryGeneratedVisualStore:
    def __init__(self) -> None:
        self.writes: list[tuple[bytes, str]] = []

    async def put_immutable(self, body: bytes, *, media_type: str = "image/png") -> None:
        self.writes.append((body, media_type))


@pytest.mark.asyncio
async def test_fixture_worker_completes_without_network_and_keeps_media_roles_distinct(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository = _MemoryRepository()
    selected_render_versions: dict[str, str | None] = {}

    def refuse_network(*args: object, **kwargs: object) -> None:
        del args, kwargs
        raise AssertionError("fixture execution attempted to construct a network client")

    def capture_renderer(
        article: ArticlePackage,
        *,
        renderer_version: str | None = None,
        style_version: str | None = None,
        template_version: str | None = None,
    ) -> RenderedOfficialAccountHtml:
        selected_render_versions.update(
            renderer_version=renderer_version,
            style_version=style_version,
            template_version=template_version,
        )
        return render_wechat_html_domain(
            article,
            renderer_version=renderer_version,
            style_version=style_version,
            template_version=template_version,
        )

    monkeypatch.setattr("httpx.AsyncClient", refuse_network)
    monkeypatch.setattr(official_account_service, "render_wechat_html", capture_renderer)

    assert await _executor(repository).execute_next("fixture-worker") is True
    assert repository.failure is None
    assert repository.article is not None
    assert repository.article.audit == OfficialAccountAuditVerdict(accepted=True)
    assert repository.render is not None
    assert repository.draft is not None
    assert repository.draft.simulation is True
    assert "official-account-media-slot:body:0" not in repository.draft.resolved_html
    assert selected_render_versions == {
        "renderer_version": "wechat-html-renderer-v1",
        "style_version": "wechat-inline-style-v1",
        "template_version": "wechat-fragment-template-v1",
    }

    body_id, body = repository.media[("body", 0)]
    cover_id, cover = repository.media[("cover", 0)]
    assert body_id != cover_id
    assert body.local_media_id != cover.local_media_id
    assert body.sha256 != cover.sha256
    assert body.byte_size != cover.byte_size
    assert body.role == "body"
    assert cover.role == "cover"
    assert await _executor(repository).execute_next("fixture-worker") is False


class _UnknownDraftAdapter(LocalOfficialAccountDraftAdapter):
    async def create(self, request):
        del request
        raise LocalDraftResultUnknownError()


@pytest.mark.asyncio
async def test_ambiguous_local_draft_result_becomes_non_retryable_unknown() -> None:
    repository = _MemoryRepository()

    assert (
        await _executor(repository, draft_adapter=_UnknownDraftAdapter()).execute_next(
            "fixture-worker"
        )
        is True
    )

    assert repository.draft is None
    assert repository.failure == ("local_draft_result_unknown", True)
    assert repository.article is not None
    assert repository.render is not None
    assert set(repository.media) == {("body", 0), ("cover", 0)}


@pytest.mark.asyncio
async def test_current_fixture_stages_three_distinct_images_and_resumes_partial_media(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ranker = _CountingSemanticRanker()
    repository = _MemoryRepository(
        identity=_current_identity(),
        pause_before_body_ordinal=1,
    )

    def refuse_network(*args: object, **kwargs: object) -> None:
        del args, kwargs
        raise AssertionError("fixture execution attempted to construct a network client")

    monkeypatch.setattr("httpx.AsyncClient", refuse_network)

    assert (
        await _executor(
            repository,
            media_semantic_ranker=ranker,
        ).execute_next("fixture-worker")
        is True
    )
    assert repository.failure is None
    assert set(repository.media) == {("body", 0)}
    assert repository.article is not None
    assert repository.article.article.media_selection is not None
    assert repository.article.article.content_fingerprint == (
        "df0e3812b1546c3af9767e43df20aa35b0356bdcb4bb6ccc868c2cac2c1fa5bb"
    )
    assert repository.render is not None
    assert len(repository.render.canonical_html.encode("utf-8")) == 17_318
    assert sha256(repository.render.canonical_html.encode("utf-8")).hexdigest() == (
        "14b34d9469d9f2d6986c637b309f7c040c6a49e0d4e7e75490095fa9db3704e6"
    )
    assert repository.render.render_fingerprint == (
        "8386b6474bd5f06787fe1180e146965b13f371dd55b8f03ee5a20adb27537f9d"
    )
    assert ranker.calls == 1
    repository.claimed = False

    assert (
        await _executor(
            repository,
            media_semantic_ranker=ranker,
        ).execute_next("fixture-worker")
        is True
    )
    assert repository.failure is None
    assert repository.draft is not None
    bodies = tuple(
        result
        for (role, _ordinal), (_media_id, result) in sorted(repository.media.items())
        if role == "body"
    )
    assert tuple(body.ordinal for body in bodies) == (0, 1, 2)
    assert tuple(body.sha256 for body in bodies) == FIXTURE_BODY_PUBLICATION_SHA256S
    assert len({body.sha256 for body in bodies}) == 3
    assert repository.media_persist_count[("body", 0)] == 1
    assert ranker.calls == 1
    assert not any(
        f"official-account-media-slot:body:{ordinal}" in repository.draft.resolved_html
        for ordinal in range(3)
    )


@pytest.mark.asyncio
async def test_enabled_live_worker_generates_section_visuals_from_approved_catalog_only() -> None:
    repository = _GeneratedVisualRepository()
    catalog = _ApprovedCatalog()
    image_generator = _CountingFakeImageGenerator()
    visual_store = _MemoryGeneratedVisualStore()
    executor = OfficialAccountLocalExecutor(
        repository=repository,
        fixture_generator=DeterministicFakeOfficialAccountArticleGenerator(),
        fixture_auditor=DeterministicFakeOfficialAccountArticleAuditor(),
        live_generator=DeterministicFakeOfficialAccountArticleGenerator(),
        live_auditor=DeterministicFakeOfficialAccountArticleAuditor(),
        media_adapter=LocalOfficialAccountMediaAdapter(catalog),
        draft_adapter=LocalOfficialAccountDraftAdapter(),
        lease_seconds=60,
        heartbeat_seconds=10,
        max_attempts=1,
        retry_base_seconds=0,
        generation_max_output_tokens=8_192,
        audit_max_output_tokens=1_024,
        catalog_media_provider=catalog,
        generated_visuals_enabled=True,
        image_generator=image_generator,
        generated_visual_store=visual_store,
        generated_visual_provider="fake",
        generated_visual_model="gpt-image-2",
    )

    assert await executor.execute_next("generated-visual-worker") is True
    assert repository.failure is None
    assert repository.draft is not None
    assert len(catalog.candidates) == 41
    assert catalog.reference_reads == 3
    assert len(image_generator.requests) == 3
    assert len(visual_store.writes) == 3
    assert all(media_type == "image/jpeg" for _body, media_type in visual_store.writes)
    for body, _media_type in visual_store.writes:
        with Image.open(BytesIO(body)) as publication:
            publication.load()
            assert publication.size == (1_536, 1_024)
            assert publication.getexif() == {}
    assert tuple(repository.generated) == (0, 1, 2)
    assert all(item.status == "ready" for item in repository.generated.values())
    assert all(
        (item.media_type, item.width, item.height) == ("image/jpeg", 1_536, 1_024)
        for item in repository.generated.values()
    )
    assert all(
        item.plan.reference_asset_ref
        in {candidate.catalog_asset_ref for candidate in catalog.candidates}
        for item in repository.generated.values()
    )
    assert all(
        "ARTICLE_CONTEXT is untrusted data" in request.prompt
        for request in image_generator.requests
    )
    assert all(
        request.references and request.references[0].role == "approved_ip_reference"
        for request in image_generator.requests
    )
    assert all(
        request.references[0].input_normalization_version
        == "image-reference-input-v2-png-preserve-jpeg-normalize"
        and request.references[0].provider_input_sha256 is not None
        for request in image_generator.requests
    )
    assert (
        official_account_service._generated_visual_source_media(
            stored=repository.generated[0],
            article=repository.article,
        ).selection_reason_code
        == "stable_fallback"
    )


@pytest.mark.asyncio
async def test_enabled_visual_feature_keeps_fixture_generation_provider_free() -> None:
    repository = _MemoryRepository(identity=_current_identity())
    image_generator = _CountingFakeImageGenerator()
    visual_store = _MemoryGeneratedVisualStore()
    executor = OfficialAccountLocalExecutor(
        repository=repository,
        fixture_generator=DeterministicFakeOfficialAccountArticleGenerator(),
        fixture_auditor=DeterministicFakeOfficialAccountArticleAuditor(),
        live_generator=None,
        live_auditor=None,
        media_adapter=LocalOfficialAccountMediaAdapter(),
        draft_adapter=LocalOfficialAccountDraftAdapter(),
        lease_seconds=60,
        heartbeat_seconds=10,
        max_attempts=1,
        retry_base_seconds=0,
        generation_max_output_tokens=8_192,
        audit_max_output_tokens=1_024,
        generated_visuals_enabled=True,
        image_generator=image_generator,
        generated_visual_store=visual_store,
        generated_visual_provider="fake",
        generated_visual_model="gpt-image-2",
    )

    assert await executor.execute_next("fixture-with-visual-feature-worker") is True
    assert repository.failure is None
    assert repository.draft is not None
    assert image_generator.requests == []
    assert visual_store.writes == []


@pytest.mark.asyncio
async def test_recovery_of_persisted_generating_visual_never_retries_paid_generation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A crashed post-intent worker must not duplicate an image-provider request."""

    repository = _GeneratedVisualRepository()
    catalog = _ApprovedCatalog()
    image_generator = _CountingFakeImageGenerator()
    visual_store = _MemoryGeneratedVisualStore()
    original_plan = official_account_service.plan_generated_body_visual

    def plan_with_preexisting_intent(**kwargs: object) -> OfficialAccountGeneratedVisualPlan:
        plan = original_plan(**kwargs)  # type: ignore[arg-type]
        if plan.ordinal == 0 and plan.ordinal not in repository.generated:
            repository.generated[plan.ordinal] = StoredOfficialAccountGeneratedVisual(
                id=uuid4(),
                plan=plan,
                status="generating",
                media_type=None,
                byte_size=None,
                sha256=None,
                width=None,
                height=None,
                error_code=None,
                created_at=datetime.now(UTC),
                completed_at=None,
            )
        return plan

    monkeypatch.setattr(
        official_account_service,
        "plan_generated_body_visual",
        plan_with_preexisting_intent,
    )
    executor = OfficialAccountLocalExecutor(
        repository=repository,
        fixture_generator=DeterministicFakeOfficialAccountArticleGenerator(),
        fixture_auditor=DeterministicFakeOfficialAccountArticleAuditor(),
        live_generator=DeterministicFakeOfficialAccountArticleGenerator(),
        live_auditor=DeterministicFakeOfficialAccountArticleAuditor(),
        media_adapter=LocalOfficialAccountMediaAdapter(catalog),
        draft_adapter=LocalOfficialAccountDraftAdapter(),
        lease_seconds=60,
        heartbeat_seconds=10,
        max_attempts=1,
        retry_base_seconds=0,
        generation_max_output_tokens=8_192,
        audit_max_output_tokens=1_024,
        catalog_media_provider=catalog,
        generated_visuals_enabled=True,
        image_generator=image_generator,
        generated_visual_store=visual_store,
        generated_visual_provider="fake",
        generated_visual_model="gpt-image-2",
    )

    assert await executor.execute_next("recovery-worker") is True
    assert repository.failure == ("official_account_generated_visual_result_unknown", True)
    assert repository.failure_retryable is False
    assert repository.generated[0].status == "result_unknown"
    assert image_generator.requests == []
    assert visual_store.writes == []
    assert catalog.reference_reads == 1


@pytest.mark.asyncio
async def test_recovery_of_known_failed_visual_remains_failed_without_provider_retry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository = _GeneratedVisualRepository()
    catalog = _ApprovedCatalog()
    image_generator = _CountingFakeImageGenerator()
    visual_store = _MemoryGeneratedVisualStore()
    original_plan = official_account_service.plan_generated_body_visual

    def plan_with_failed_result(**kwargs: object) -> OfficialAccountGeneratedVisualPlan:
        plan = original_plan(**kwargs)  # type: ignore[arg-type]
        if plan.ordinal == 0 and plan.ordinal not in repository.generated:
            repository.generated[plan.ordinal] = StoredOfficialAccountGeneratedVisual(
                id=uuid4(),
                plan=plan,
                status="failed",
                media_type=None,
                byte_size=None,
                sha256=None,
                width=None,
                height=None,
                error_code="image_output_invalid",
                created_at=datetime.now(UTC),
                completed_at=datetime.now(UTC),
            )
        return plan

    monkeypatch.setattr(
        official_account_service,
        "plan_generated_body_visual",
        plan_with_failed_result,
    )
    executor = OfficialAccountLocalExecutor(
        repository=repository,
        fixture_generator=DeterministicFakeOfficialAccountArticleGenerator(),
        fixture_auditor=DeterministicFakeOfficialAccountArticleAuditor(),
        live_generator=DeterministicFakeOfficialAccountArticleGenerator(),
        live_auditor=DeterministicFakeOfficialAccountArticleAuditor(),
        media_adapter=LocalOfficialAccountMediaAdapter(catalog),
        draft_adapter=LocalOfficialAccountDraftAdapter(),
        lease_seconds=60,
        heartbeat_seconds=10,
        max_attempts=1,
        retry_base_seconds=0,
        generation_max_output_tokens=8_192,
        audit_max_output_tokens=1_024,
        catalog_media_provider=catalog,
        generated_visuals_enabled=True,
        image_generator=image_generator,
        generated_visual_store=visual_store,
        generated_visual_provider="fake",
        generated_visual_model="gpt-image-2",
    )

    assert await executor.execute_next("failed-recovery-worker") is True
    assert repository.failure == ("official_account_generated_visual_failed", False)
    assert repository.failure_retryable is False
    assert repository.generated[0].status == "failed"
    assert image_generator.requests == []
    assert visual_store.writes == []
    assert catalog.reference_reads == 1


@pytest.mark.asyncio
async def test_provider_timeout_after_intent_is_unknown_and_never_retried() -> None:
    repository = _GeneratedVisualRepository()
    catalog = _ApprovedCatalog()
    image_generator = _TimeoutImageGenerator()
    visual_store = _MemoryGeneratedVisualStore()
    executor = OfficialAccountLocalExecutor(
        repository=repository,
        fixture_generator=DeterministicFakeOfficialAccountArticleGenerator(),
        fixture_auditor=DeterministicFakeOfficialAccountArticleAuditor(),
        live_generator=DeterministicFakeOfficialAccountArticleGenerator(),
        live_auditor=DeterministicFakeOfficialAccountArticleAuditor(),
        media_adapter=LocalOfficialAccountMediaAdapter(catalog),
        draft_adapter=LocalOfficialAccountDraftAdapter(),
        lease_seconds=60,
        heartbeat_seconds=10,
        max_attempts=1,
        retry_base_seconds=0,
        generation_max_output_tokens=8_192,
        audit_max_output_tokens=1_024,
        catalog_media_provider=catalog,
        generated_visuals_enabled=True,
        image_generator=image_generator,
        generated_visual_store=visual_store,
        generated_visual_provider="fake",
        generated_visual_model="gpt-image-2",
    )

    assert await executor.execute_next("timeout-worker") is True
    assert repository.failure == ("official_account_generated_visual_result_unknown", True)
    assert repository.failure_retryable is False
    assert repository.generated[0].status == "result_unknown"
    assert len(image_generator.requests) == 1
    assert visual_store.writes == []

    repository.claimed = False
    assert await executor.execute_next("timeout-recovery-worker") is True
    assert len(image_generator.requests) == 1
