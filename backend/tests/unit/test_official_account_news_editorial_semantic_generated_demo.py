# ruff: noqa: RUF001 -- Chinese editorial assertions are intentional.
from __future__ import annotations

import json
import socket
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import replace
from hashlib import sha256
from io import BytesIO
from pathlib import Path
from typing import Any

import pytest
from app import official_account_news_editorial_asset_rich_demo as asset_rich_v4
from app import official_account_news_editorial_polished_demo as polished_v3
from app import official_account_news_editorial_semantic_generated_demo as semantic_v5
from app.application.ports.image_generation import (
    ImageGenerationRequest,
    ImageGenerationResult,
)
from app.application.ports.official_account_local import OfficialAccountSourceMedia
from app.core.config import Settings
from app.domain.official_account_local import (
    ArticleImageBlock,
    article_package_fingerprint,
    body_media_placeholder,
)
from app.domain.visual_retrieval import (
    VISUAL_EMBEDDING_INPUT_POLICY_V1,
    VisualEmbeddingIdentity,
    VisualEmbeddingRequest,
    VisualEmbeddingResult,
    VisualSemanticRanking,
    VisualSemanticScore,
)
from app.official_account_news_editorial_demo import EditorialSourceBundle
from PIL import Image
from pydantic import SecretStr

_ALIBABA_ENDPOINT = (
    "https://workspace.cn-beijing.maas.aliyuncs.com/api/v1/services/embeddings/"
    "multimodal-embedding/multimodal-embedding"
)


def _read_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_bytes())
    assert isinstance(payload, dict)
    return payload


def _jpeg_bytes(color: tuple[int, int, int], *, size: tuple[int, int] = (1536, 1024)) -> bytes:
    stream = BytesIO()
    Image.new("RGB", size, color=color).save(
        stream,
        format="JPEG",
        quality=82,
        subsampling=2,
        optimize=False,
        progressive=False,
        exif=b"",
        icc_profile=None,
    )
    return stream.getvalue()


def _png_bytes(color: tuple[int, int, int]) -> bytes:
    stream = BytesIO()
    Image.new("RGB", (1024, 1024), color=color).save(stream, format="PNG")
    return stream.getvalue()


def _bundle() -> EditorialSourceBundle:
    image_bodies = (
        _jpeg_bytes((211, 231, 245)),
        _jpeg_bytes((229, 215, 188)),
        _jpeg_bytes((198, 225, 215)),
    )
    checksums = tuple(sha256(body).hexdigest() for body in image_bodies)
    evidence_ids = sorted(polished_v3._EXPECTED_EVIDENCE_IDS, key=str)
    sources = (
        {
            "canonical_url": semantic_v5.NEWS_URL,
            "document_sha256": "a" * 64,
            "evidence_id": str(evidence_ids[0]),
            "exact_quote": "科技教育以更加鲜明的学科融合和实践导向持续发力",
            "published_date": "2026-07-21",
            "retrieval_url": semantic_v5.NEWS_URL,
            "source_name": "中华人民共和国教育部政府门户网站",
            "title": "面向未来，向新而行",
        },
        {
            "canonical_url": semantic_v5.PLAN_URL,
            "document_sha256": "b" * 64,
            "evidence_id": str(evidence_ids[1]),
            "exact_quote": "鼓励开展人工智能跨学科教学",
            "published_date": "2026-04-10",
            "retrieval_url": semantic_v5.PLAN_URL,
            "source_name": "中华人民共和国教育部政府门户网站",
            "title": "教育部等五部门关于印发《“人工智能+教育”行动计划》的通知",
        },
    )
    rows: tuple[dict[str, Any], dict[str, Any], dict[str, Any]] = (
        {
            "output": {"sha256": checksums[0]},
            "ip_visibility_assessment": "pass",
            "reference_public_ref": "33586a916bbbfbf1",
        },
        {
            "output": {"sha256": checksums[1]},
            "ip_visibility_assessment": "pass",
            "reference_public_ref": "5c2a29bbec16ca4f",
        },
        {
            "output": {"sha256": checksums[2]},
            "ip_visibility_assessment": "pass",
            "reference_public_ref": "09c8fd9470cb5502",
        },
    )
    return EditorialSourceBundle(
        evidence_sources=sources,
        visual_rows=rows,
        image_bodies=image_bodies,
        image_checksums=(checksums[0], checksums[1], checksums[2]),
        source_content_fingerprint="1" * 64,
        source_render_fingerprint="2" * 64,
        source_run_id="6014f5cc-1755-507a-9ecb-ab72fa41071e",
        source_manifest_sha256="3" * 64,
    )


def _historical_refs() -> frozenset[str]:
    return frozenset(str(row["reference_public_ref"]) for row in _bundle().visual_rows)


class _FakeCatalogProvider:
    def __init__(self, *, current: bool = True, drift: bool = False) -> None:
        self.current = current
        self.drift = drift
        self.load_calls = 0
        self.current_calls = 0
        self.revalidate_calls = 0
        self.read_calls = 0
        candidates: list[OfficialAccountSourceMedia] = []
        self.bodies: dict[str, bytes] = {}
        for index in range(41):
            asset_id = sha256(f"approved-master-{index}".encode()).hexdigest()
            public_ref = asset_id[:16]
            body = _jpeg_bytes(
                ((index * 31) % 255, (index * 47) % 255, (index * 67) % 255),
                size=(640, 640),
            )
            self.bodies[public_ref] = body
            candidates.append(
                OfficialAccountSourceMedia(
                    source_image_artifact_id=None,
                    fixture_id=f"catalog:{public_ref}",
                    media_type="image/jpeg",
                    byte_size=len(body),
                    sha256=sha256(body).hexdigest(),
                    semantic_label=f"小赛场景 {index}",
                    candidate_id=public_ref,
                    semantic_tags=("science", "observe", f"scene-{index}"),
                    alt_text=f"小赛科学观察场景 {index}",
                    caption_text=f"观察、记录与验证 {index}",
                    publication_priority=index,
                    catalog_asset_id=asset_id,
                    catalog_asset_ref=public_ref,
                    catalog_version="brand-visual-catalog-v1",
                    source_master_sha256=asset_id,
                )
            )
        self.candidates = tuple(candidates)

    async def load_candidates(self) -> tuple[OfficialAccountSourceMedia, ...]:
        self.load_calls += 1
        return self.candidates

    async def revalidate_candidate(
        self, candidate: OfficialAccountSourceMedia
    ) -> OfficialAccountSourceMedia:
        self.revalidate_calls += 1
        return replace(candidate, byte_size=candidate.byte_size + 1) if self.drift else candidate

    async def catalog_is_current(self, candidates: tuple[OfficialAccountSourceMedia, ...]) -> bool:
        self.current_calls += 1
        assert candidates == self.candidates
        return self.current

    async def read_publication_bytes(self, **kwargs: object) -> bytes:
        self.read_calls += 1
        public_ref = str(kwargs["catalog_asset_ref"])
        candidate = next(item for item in self.candidates if item.candidate_id == public_ref)
        assert kwargs == {
            "catalog_asset_ref": public_ref,
            "catalog_version": candidate.catalog_version,
            "source_master_sha256": candidate.source_master_sha256,
            "publication_sha256": candidate.sha256,
        }
        return self.bodies[public_ref]


class _FakeEmbeddings:
    def __init__(self) -> None:
        self.requests: list[VisualEmbeddingRequest] = []

    async def embed_visual(self, request: VisualEmbeddingRequest) -> VisualEmbeddingResult:
        self.requests.append(request)
        return VisualEmbeddingResult(
            identity=request.identity,
            input_sha256=request.input_sha256,
            request_fingerprint=request.request_fingerprint,
            vector=(1.0, *(0.0 for _ in range(request.identity.dimensions - 1))),
            input_tokens=12,
            latency_ms=3,
        )


class _FakeRepository:
    def __init__(
        self,
        *,
        complete: bool = True,
        partial_result: bool = False,
        preferred_asset_ids: tuple[str, str] | None = None,
    ) -> None:
        self.complete = complete
        self.partial_result = partial_result
        self.preferred_asset_ids = preferred_asset_ids
        self.prove_calls = 0
        self.search_calls = 0
        self.catalog_assets: tuple[tuple[str, str], ...] = ()

    async def prove_complete_catalog(self, **kwargs: object) -> bool:
        self.prove_calls += 1
        self.catalog_assets = kwargs["catalog_assets"]  # type: ignore[assignment]
        assert len(self.catalog_assets) == 41
        return self.complete

    async def search_complete_catalog(self, **kwargs: object) -> VisualSemanticRanking:
        query = kwargs["query"]
        assert isinstance(query, VisualEmbeddingResult)
        identity = kwargs["identity"]
        assert isinstance(identity, VisualEmbeddingIdentity)
        assets = tuple(self.catalog_assets[:-1] if self.partial_result else self.catalog_assets)
        preferred_asset_id = (
            self.preferred_asset_ids[self.search_calls]
            if self.preferred_asset_ids is not None
            else assets[39 if self.search_calls == 0 else 40][0]
        )
        scores = tuple(
            VisualSemanticScore(
                asset_id=asset_id,
                similarity=(0.95 if asset_id == preferred_asset_id else 0.05 - index / 10_000),
            )
            for index, (asset_id, _checksum) in enumerate(assets)
        )
        self.search_calls += 1
        return VisualSemanticRanking(
            catalog_version=str(kwargs["catalog_version"]),
            identity=identity,
            query_fingerprint=query.request_fingerprint,
            scores=scores,
            indexed_asset_count=len(scores),
            catalog_asset_count=(41 if self.partial_result else len(scores)),
            complete=not self.partial_result,
        )

    async def claim_asset(self, **_kwargs: object) -> None:
        raise AssertionError("index mutation is forbidden in v5")

    async def persist_embedding(self, **_kwargs: object) -> bool:
        raise AssertionError("index mutation is forbidden in v5")

    async def fail_asset(self, **_kwargs: object) -> bool:
        raise AssertionError("index mutation is forbidden in v5")


class _FakeImageGenerator:
    def __init__(self, *, timeout_on: int | None = None, attempts: int = 1) -> None:
        self.timeout_on = timeout_on
        self.attempts = attempts
        self.requests: list[ImageGenerationRequest] = []

    async def generate(self, request: ImageGenerationRequest) -> ImageGenerationResult:
        self.requests.append(request)
        if self.timeout_on == len(self.requests):
            from app.core.errors import ImageProviderTimeoutError

            raise ImageProviderTimeoutError()
        body = _png_bytes((245, 176, 70) if len(self.requests) == 1 else (74, 132, 224))
        return ImageGenerationResult(
            provider="toapis",
            model="gpt-image-2",
            request_fingerprint=request.request_fingerprint,
            provider_task_id=f"safe-task-{len(self.requests)}",
            provider_upload_id=f"safe-upload-{len(self.requests)}",
            image_bytes=body,
            media_type="image/png",
            width=1024,
            height=1024,
            attempts=self.attempts,
        )


class _Contexts:
    def __init__(
        self,
        *,
        embeddings: _FakeEmbeddings | None = None,
        images: _FakeImageGenerator | None = None,
    ) -> None:
        self.embeddings = embeddings or _FakeEmbeddings()
        self.images = images or _FakeImageGenerator()
        self.embedding_enters = 0
        self.image_enters = 0

    @asynccontextmanager
    async def embedding_context(self) -> AsyncIterator[_FakeEmbeddings]:
        self.embedding_enters += 1
        yield self.embeddings

    @asynccontextmanager
    async def image_context(self) -> AsyncIterator[_FakeImageGenerator]:
        self.image_enters += 1
        yield self.images


def _block_network(monkeypatch: pytest.MonkeyPatch) -> None:
    def blocked_connect(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("network access is forbidden in v5 unit tests")

    monkeypatch.setattr(socket.socket, "connect", blocked_connect)


def test_build_and_render_v5_preserve_article_contract_with_five_3_by_2_scenes() -> None:
    article = semantic_v5.build_semantic_article(_bundle())
    html = semantic_v5.render_semantic_generated_html(article)

    assert article.versions == semantic_v5._versions()
    assert semantic_v5.DEFAULT_OUTPUT_DIR == Path(
        "output/official-account-news-ip-editorial-semantic-generated-20260825-v5"
    )
    assert article.content_fingerprint == article_package_fingerprint(article)
    assert len(article.sections) == 6
    assert tuple(
        (section_index, block.slot_key)
        for section_index, section in enumerate(article.sections)
        for block in section.blocks
        if isinstance(block, ArticleImageBlock)
    ) == ((0, "body-0"), (1, "body-3"), (2, "body-1"), (3, "body-4"), (4, "body-2"))
    assert html.count("<h1 ") == 1
    assert html.count("<img ") == 5
    assert html.count('data-module="semantic-generated-scene"') == 2
    assert 'data-module="catalog-cutaway"' not in html
    assert "aspect-ratio:3/2" in html
    assert "object-fit:contain" not in html
    for ordinal in range(5):
        assert html.count(body_media_placeholder(ordinal)) == 1
    for ordinal, alt_text in semantic_v5._SEMANTIC_SCENE_ALTS.items():
        block = article.sections[1 if ordinal == 3 else 3].blocks[3 if ordinal == 3 else 2]
        assert isinstance(block, ArticleImageBlock)
        assert block.alt_text == alt_text
        assert html.count(f'alt="{alt_text}"') == 1


def test_live_preflight_pins_qwen_toapis_and_one_attempt_without_mutating_settings(
    tmp_path: Path,
) -> None:
    settings = Settings(
        _env_file=None,
        visual_embedding_provider_mode="alibaba",
        visual_embedding_endpoint=SecretStr(_ALIBABA_ENDPOINT),
        visual_embedding_api_key=SecretStr("test-only-embedding-key"),
        image_provider_mode="comfly",
        comfly_base_url="https://unused-comfly.test",
        comfly_api_key=SecretStr("test-only-unused-key"),
        toapis_base_url="https://toapis.com",
        toapis_api_key=SecretStr("test-only-toapis-key"),
        image_max_attempts=3,
    )

    live = semantic_v5._preflight_live_settings(settings, tmp_path / "fresh")

    assert live.visual_embedding_identity == VisualEmbeddingIdentity()
    assert live.image_provider_mode == "toapis"
    assert live.image_max_attempts == 1
    assert settings.image_provider_mode == "comfly"
    assert settings.image_max_attempts == 3


@pytest.mark.asyncio
async def test_complete_index_is_proved_before_embedding_context_is_constructed() -> None:
    contexts = _Contexts()
    repository = _FakeRepository(complete=False)

    with pytest.raises(ValueError, match="index is incomplete"):
        await semantic_v5.select_semantic_references(
            article=semantic_v5.build_semantic_article(_bundle()),
            catalog_provider=_FakeCatalogProvider(),
            repository=repository,
            embeddings_context_factory=contexts.embedding_context,
            forbidden_public_refs=_historical_refs(),
        )

    assert repository.prove_calls == 1
    assert repository.search_calls == 0
    assert contexts.embedding_enters == 0
    assert contexts.embeddings.requests == []


@pytest.mark.asyncio
async def test_mixed_embedding_identity_fails_before_catalog_or_client_construction() -> None:
    contexts = _Contexts()
    repository = _FakeRepository()
    provider = _FakeCatalogProvider()

    with pytest.raises(ValueError, match="active v2 identity"):
        await semantic_v5.select_semantic_references(
            article=semantic_v5.build_semantic_article(_bundle()),
            catalog_provider=provider,
            repository=repository,
            embeddings_context_factory=contexts.embedding_context,
            forbidden_public_refs=_historical_refs(),
            identity=VisualEmbeddingIdentity(input_policy_version=VISUAL_EMBEDDING_INPUT_POLICY_V1),
        )

    assert provider.load_calls == 0
    assert repository.prove_calls == 0
    assert contexts.embedding_enters == 0


@pytest.mark.asyncio
async def test_two_exact_block_queries_use_full_result_fences_and_distinct_public_refs() -> None:
    provider = _FakeCatalogProvider()
    repository = _FakeRepository()
    contexts = _Contexts()

    article = semantic_v5.build_semantic_article(_bundle())
    selection = await semantic_v5.select_semantic_references(
        article=article,
        catalog_provider=provider,
        repository=repository,
        embeddings_context_factory=contexts.embedding_context,
        forbidden_public_refs=_historical_refs(),
    )

    assert repository.prove_calls == 1
    assert repository.search_calls == 2
    assert contexts.embedding_enters == 1
    assert len(contexts.embeddings.requests) == 2
    assert all(1 <= len(request.text or "") <= 2_000 for request in contexts.embeddings.requests)
    assert all("exact_source=" in (request.text or "") for request in contexts.embeddings.requests)
    parent_question_paragraphs = article.sections[1].blocks[:3]
    assert all(
        block.text in (contexts.embeddings.requests[0].text or "")
        for block in parent_question_paragraphs
        if hasattr(block, "text")
    )
    ai_child_list = article.sections[3].blocks[1]
    assert all(
        item in (contexts.embeddings.requests[1].text or "")
        for item in getattr(ai_child_list, "items", ())
    )
    assert tuple(reference.ordinal for reference in selection.references) == (3, 4)
    assert tuple(reference.section_index for reference in selection.references) == (1, 3)
    assert len({reference.public_ref for reference in selection.references}) == 2
    assert all(reference.similarity_band == "very_high" for reference in selection.references)
    assert all(len(reference.source_text_fingerprint) == 64 for reference in selection.references)
    assert provider.revalidate_calls == 2
    assert provider.read_calls == 2
    assert provider.current_calls == 3

    projection = semantic_v5._selection_projection(selection)
    serialized = json.dumps(projection, ensure_ascii=False)
    assert "exact_source=" not in serialized
    assert "approved-master" not in serialized
    assert "catalog_asset_id" not in serialized
    assert "source_master_sha256" not in serialized
    assert "private/" not in serialized
    assert "vector" not in serialized


@pytest.mark.asyncio
async def test_historical_v1_references_are_excluded_even_when_top_ranked() -> None:
    provider = _FakeCatalogProvider()
    forbidden_candidates = provider.candidates[:3]
    forbidden = frozenset(candidate.candidate_id for candidate in forbidden_candidates)
    preferred = (
        str(forbidden_candidates[0].catalog_asset_id),
        str(forbidden_candidates[1].catalog_asset_id),
    )
    repository = _FakeRepository(preferred_asset_ids=preferred)
    contexts = _Contexts()

    selection = await semantic_v5.select_semantic_references(
        article=semantic_v5.build_semantic_article(_bundle()),
        catalog_provider=provider,
        repository=repository,
        embeddings_context_factory=contexts.embedding_context,
        forbidden_public_refs=forbidden,
    )

    assert len({reference.public_ref for reference in selection.references}) == 2
    assert not ({reference.public_ref for reference in selection.references} & forbidden)


@pytest.mark.asyncio
async def test_partial_semantic_ranking_fails_before_reference_read() -> None:
    provider = _FakeCatalogProvider()
    repository = _FakeRepository(partial_result=True)
    contexts = _Contexts()

    with pytest.raises(ValueError, match="complete-result fence"):
        await semantic_v5.select_semantic_references(
            article=semantic_v5.build_semantic_article(_bundle()),
            catalog_provider=provider,
            repository=repository,
            embeddings_context_factory=contexts.embedding_context,
            forbidden_public_refs=_historical_refs(),
        )

    assert len(contexts.embeddings.requests) == 1
    assert provider.revalidate_calls == 0
    assert provider.read_calls == 0


@pytest.mark.asyncio
async def test_timeout_is_result_unknown_and_never_retries_or_calls_second_image(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _block_network(monkeypatch)
    monkeypatch.setattr(asset_rich_v4, "load_source_bundle", lambda _path: _bundle())
    generator = _FakeImageGenerator(timeout_on=1)
    contexts = _Contexts(images=generator)
    output = tmp_path / "semantic-timeout"

    ready = await semantic_v5.export_semantic_generated_bundle(
        tmp_path / "unused",
        tmp_path / "catalog.json",
        output,
        repository=_FakeRepository(),
        embeddings_context_factory=contexts.embedding_context,
        image_context_factory=contexts.image_context,
        catalog_provider=_FakeCatalogProvider(),
    )

    assert ready is False
    assert len(generator.requests) == 1
    assert contexts.image_enters == 1
    diagnostics = semantic_v5.terminal_diagnostics_path(output, "result_unknown")
    assert not output.exists()
    assert (diagnostics / "intents" / "body-3.intent.json").is_file()
    assert not (diagnostics / "intents" / "body-4.intent.json").exists()
    result = _read_json(diagnostics / "intents" / "body-3.result.json")
    run = _read_json(diagnostics / "run.json")
    assert result["state"] == "result_unknown"
    assert result["safe_error_code"] == "image_provider_timeout"
    assert result["automatic_retry_permitted"] is False
    assert run["status"] == "result_unknown"
    assert run["paid_generation_calls_attempted"] == 1
    assert run["paid_generation_calls_succeeded"] == 0
    assert run["wechat_calls"] == run["wecom_calls"] == run["publish_calls"] == 0


@pytest.mark.asyncio
async def test_provider_reported_retry_is_terminal_failed_without_second_image(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _block_network(monkeypatch)
    monkeypatch.setattr(asset_rich_v4, "load_source_bundle", lambda _path: _bundle())
    generator = _FakeImageGenerator(attempts=2)
    contexts = _Contexts(images=generator)
    output = tmp_path / "semantic-retry-rejected"

    ready = await semantic_v5.export_semantic_generated_bundle(
        tmp_path / "unused",
        tmp_path / "catalog.json",
        output,
        repository=_FakeRepository(),
        embeddings_context_factory=contexts.embedding_context,
        image_context_factory=contexts.image_context,
        catalog_provider=_FakeCatalogProvider(),
    )

    assert ready is False
    assert len(generator.requests) == 1
    diagnostics = semantic_v5.terminal_diagnostics_path(output, "failed")
    assert not output.exists()
    result = _read_json(diagnostics / "intents" / "body-3.result.json")
    assert result["state"] == "failed"
    assert result["safe_error_code"] == "image_output_invalid"
    assert not (diagnostics / "intents" / "body-4.intent.json").exists()


@pytest.mark.asyncio
async def test_publication_validation_failure_is_terminal_without_second_image(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _block_network(monkeypatch)
    monkeypatch.setattr(asset_rich_v4, "load_source_bundle", lambda _path: _bundle())

    def reject_publication(_body: bytes) -> dict[str, Any]:
        from app.core.errors import ImageOutputValidationError

        raise ImageOutputValidationError("image_output_invalid")

    monkeypatch.setattr(semantic_v5, "_validate_jpeg", reject_publication)
    contexts = _Contexts()
    output = tmp_path / "semantic-invalid-publication"

    ready = await semantic_v5.export_semantic_generated_bundle(
        tmp_path / "unused",
        tmp_path / "catalog.json",
        output,
        repository=_FakeRepository(),
        embeddings_context_factory=contexts.embedding_context,
        image_context_factory=contexts.image_context,
        catalog_provider=_FakeCatalogProvider(),
    )

    assert ready is False
    assert len(contexts.images.requests) == 1
    diagnostics = semantic_v5.terminal_diagnostics_path(output, "failed")
    assert not output.exists()
    assert _read_json(diagnostics / "run.json")["paid_generation_calls_succeeded"] == 0
    assert _read_json(diagnostics / "intents" / "body-3.result.json")["state"] == "failed"
    assert not (diagnostics / "intents" / "body-4.intent.json").exists()


@pytest.mark.asyncio
async def test_success_export_is_byte_exact_redacted_no_clobber_and_deterministic(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _block_network(monkeypatch)
    bundle = _bundle()
    monkeypatch.setattr(asset_rich_v4, "load_source_bundle", lambda _path: bundle)
    first = tmp_path / "first" / "semantic-bundle"
    second = tmp_path / "second" / "semantic-bundle"

    async def run(output: Path) -> _Contexts:
        contexts = _Contexts()
        assert await semantic_v5.export_semantic_generated_bundle(
            tmp_path / "unused",
            tmp_path / "catalog.json",
            output,
            repository=_FakeRepository(),
            embeddings_context_factory=contexts.embedding_context,
            image_context_factory=contexts.image_context,
            catalog_provider=_FakeCatalogProvider(),
        )
        return contexts

    first_contexts = await run(first)
    second_contexts = await run(second)

    assert len(first_contexts.embeddings.requests) == 2
    assert len(first_contexts.images.requests) == 2
    assert len(second_contexts.embeddings.requests) == 2
    assert len(second_contexts.images.requests) == 2
    for ordinal, expected in enumerate(bundle.image_bodies):
        assert (first / "assets" / f"body-{ordinal:02d}.jpg").read_bytes() == expected
    generated = tuple(
        (first / "assets" / f"body-{ordinal:02d}.jpg").read_bytes() for ordinal in (3, 4)
    )
    assert len({sha256(body).hexdigest() for body in generated}) == 2
    assert all(semantic_v5._validate_jpeg(body)["metadata_free"] for body in generated)
    assert (first / "semantic-bundle.zip").read_bytes() == (
        second / "semantic-bundle.zip"
    ).read_bytes()

    html = (first / "article-body.html").read_text(encoding="utf-8")
    assert html.count('src="assets/body-') == 5
    assert html.count('data-module="semantic-generated-scene"') == 2
    assert "__OFFICIAL_ACCOUNT_BODY_MEDIA_" not in html
    preview = (first / "preview.html").read_text(encoding="utf-8")
    assert "default-src 'none'" in preview
    assert "img-src 'self'" in preview
    run_payload = _read_json(first / "run.json")
    manifest = _read_json(first / "manifest.json")
    assert run_payload["embedding_provider_calls"] == 2
    assert run_payload["paid_generation_calls_attempted"] == 2
    assert run_payload["paid_generation_calls_succeeded"] == 2
    assert run_payload["automatic_retry_permitted"] is False
    assert all(
        run_payload[field] == 0
        for field in ("comfly_calls", "wechat_calls", "wecom_calls", "publish_calls")
    )
    assert all(
        manifest[field] == 0
        for field in ("comfly_calls", "wechat_calls", "wecom_calls", "publish_calls")
    )
    safe_files = (
        first / "semantic-selection.json",
        first / "visual-map.json",
        first / "run.json",
        first / "manifest.json",
        first / "intents" / "body-3.intent.json",
        first / "intents" / "body-4.intent.json",
    )
    serialized = "\n".join(path.read_text(encoding="utf-8") for path in safe_files)
    assert "exact_block=" not in serialized
    assert "catalog_asset_id" not in serialized
    assert "source_master_sha256" not in serialized
    assert "provider_task_id" not in serialized
    assert "provider_upload_id" not in serialized
    assert "private/" not in serialized
    assert '"prompt":' not in serialized
    assert "paragraph-1=" not in serialized
    assert "structured_ai_child_boundary_list" not in serialized
    visual_rows = _read_json(first / "visual-map.json")["visuals"]
    assert {
        int(row["ordinal"]): str(row["semantic_alt"])
        for row in visual_rows
        if int(row["ordinal"]) in (3, 4)
    } == semantic_v5._SEMANTIC_SCENE_ALTS

    with pytest.raises(FileExistsError, match="refusing to replace"):
        await semantic_v5.export_semantic_generated_bundle(
            tmp_path / "unused",
            tmp_path / "catalog.json",
            first,
            repository=_FakeRepository(),
            embeddings_context_factory=_Contexts().embedding_context,
            image_context_factory=_Contexts().image_context,
            catalog_provider=_FakeCatalogProvider(),
        )


@pytest.mark.asyncio
async def test_catalog_drift_fails_before_image_client_construction(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _block_network(monkeypatch)
    monkeypatch.setattr(asset_rich_v4, "load_source_bundle", lambda _path: _bundle())
    contexts = _Contexts()

    with pytest.raises(ValueError, match="changed during revalidation"):
        await semantic_v5.export_semantic_generated_bundle(
            tmp_path / "unused",
            tmp_path / "catalog.json",
            tmp_path / "never-created",
            repository=_FakeRepository(),
            embeddings_context_factory=contexts.embedding_context,
            image_context_factory=contexts.image_context,
            catalog_provider=_FakeCatalogProvider(drift=True),
        )

    assert contexts.image_enters == 0
    assert not (tmp_path / "never-created").exists()
