import asyncio
from dataclasses import fields, replace
from hashlib import sha256
from io import BytesIO
from types import SimpleNamespace

import pytest
from app.application.ports.official_account_local import OfficialAccountSourceMedia
from app.application.services.official_account_strict_visual import (
    execute_strict_visuals,
    strict_catalog_candidates,
    validate_xiaosai_references,
    xiaosai_catalog_candidates,
)
from app.core.errors import AppError
from app.domain.official_account_visual_pipeline import (
    OBSERVE_VISUAL_PIPELINE_VERSION,
    OFFICIAL_ACCOUNT_GENERATED_VISUAL_PROMPT_V4_VERSION,
    OFFICIAL_ACCOUNT_GENERATED_VISUAL_PROMPT_V5_VERSION,
)
from app.infrastructure.brand.visual_catalog import load_visual_catalog
from app.infrastructure.official_account_catalog import (
    LocalOfficialAccountCatalogMediaProvider,
    _candidate_from_asset,
)
from PIL import Image
from test_official_account_strict_visual_worker import _components
from test_visual_assets import _manifest_entry, _write_manifest


def make_catalog(tmp_path, groups, *, size=640):
    entries = []
    for index, characters in enumerate(groups):
        buffer = BytesIO()
        color = ((index * 37 + 20) % 256, (index * 17 + 90) % 256, (index * 53 + 170) % 256, 255)
        Image.new("RGBA", (size, size), color).save(buffer, "PNG")
        entries.append(
            _manifest_entry(
                tmp_path,
                f"05-visual-assets/reference-{index}.png",
                buffer.getvalue(),
                width=size,
                height=size,
                characters=list(characters),
                asset_kind="identity",
                display_name="小赛形象参考",
                selection_tags=["xiao-sai", "education"],
            )
        )
    manifest = _write_manifest(tmp_path, entries)
    loaded = load_visual_catalog(manifest)
    candidates = tuple(_candidate_from_asset(loaded, asset) for asset in loaded.catalog.assets)
    return LocalOfficialAccountCatalogMediaProvider(manifest), manifest, entries, candidates


@pytest.mark.parametrize(
    "characters",
    [("xiao-sai",), ("sai-xiansheng",), ("xiao-sai", "sai-xiansheng"), (), ("unknown",)],
)
async def test_real_catalog_character_lookup_ignores_forged_labels(tmp_path, characters):
    provider, _manifest, _entries, candidates = make_catalog(tmp_path, [characters])
    forged = replace(
        candidates[0],
        semantic_label="小赛 only",
        semantic_tags=("xiao-sai",),
        caption_text="小赛",
        alt_text="小赛",
    )
    assert set(await provider.reference_characters(forged)) == set(characters)
    assert "characters" not in {field.name for field in fields(OfficialAccountSourceMedia)}


@pytest.mark.parametrize(
    "mutation",
    [
        {"catalog_asset_id": "a" * 64},
        {"catalog_asset_ref": "a" * 16},
        {"catalog_version": "unrelated-catalog"},
        {"source_master_sha256": "b" * 64},
        {"sha256": "c" * 64},
        {"byte_size": 1},
    ],
)
async def test_real_character_lookup_requires_bound_catalog_and_bytes(tmp_path, mutation):
    provider, _manifest, _entries, candidates = make_catalog(tmp_path, [("xiao-sai",)])
    with pytest.raises(ValueError):
        await provider.reference_characters(replace(candidates[0], **mutation))


async def test_character_metadata_is_reread_and_master_tampering_is_rejected(tmp_path):
    provider, _manifest, entries, candidates = make_catalog(tmp_path, [("xiao-sai",)])
    assert await provider.reference_characters(candidates[0]) == ("xiao-sai",)
    entries[0]["characters"] = ["sai-xiansheng"]
    _write_manifest(tmp_path, entries)
    assert await provider.reference_characters(candidates[0]) == ("sai-xiansheng",)
    (tmp_path / entries[0]["relative_path"]).write_bytes(b"changed master")
    with pytest.raises(ValueError):
        await provider.reference_characters(candidates[0])


async def test_global_41_catalog_remains_unfiltered_and_publication_bound(tmp_path):
    groups = [("xiao-sai",)] * 15 + [("sai-xiansheng",)] * 18 + [("xiao-sai", "sai-xiansheng")] * 8
    provider, _manifest, _entries, candidates = make_catalog(tmp_path, groups)
    admitted = await provider.load_candidates()
    assert admitted == candidates and len(admitted) == 41
    assert await provider.catalog_is_current(admitted)
    distribution = {}
    for candidate in admitted:
        characters = frozenset(await provider.reference_characters(candidate))
        distribution[characters] = distribution.get(characters, 0) + 1
        publication = await provider.read_publication_bytes(
            catalog_asset_ref=candidate.catalog_asset_ref,
            catalog_version=candidate.catalog_version,
            source_master_sha256=candidate.source_master_sha256,
            publication_sha256=candidate.sha256,
        )
        assert sha256(publication).hexdigest() == candidate.sha256
    assert distribution == {
        frozenset({"xiao-sai"}): 15,
        frozenset({"sai-xiansheng"}): 18,
        frozenset({"xiao-sai", "sai-xiansheng"}): 8,
    }


async def test_real_selection_uses_exact_characters_and_rechecks_metadata_drift(tmp_path):
    groups = [("xiao-sai",), ("sai-xiansheng",), ("xiao-sai", "sai-xiansheng"), (), ("unknown",)]
    provider, _manifest, entries, candidates = make_catalog(tmp_path, groups)
    full = await strict_catalog_candidates(provider, candidates)
    selected = await xiaosai_catalog_candidates(provider, full)
    assert selected == (candidates[0],) and len(full) == 5
    await validate_xiaosai_references(provider, selected * 5)
    entries[0]["characters"] = ["sai-xiansheng"]
    _write_manifest(tmp_path, entries)
    with pytest.raises(AppError, match="Xiaosai-only"):
        await validate_xiaosai_references(provider, selected * 5)
    with pytest.raises(AppError, match="Xiaosai-only"):
        await xiaosai_catalog_candidates(provider, candidates)


@pytest.mark.parametrize("bad_characters", [("sai-xiansheng",), ("xiao-sai", "sai-xiansheng"), ()])
async def test_fifth_wrong_real_reference_blocks_before_any_paid_or_resume_claim(
    tmp_path, monkeypatch, bad_characters
):
    provider, _manifest, _entries, candidates = make_catalog(
        tmp_path, [("xiao-sai",)] * 4 + [bad_characters]
    )
    checked = []
    original = provider.reference_characters

    async def record(candidate):
        checked.append(candidate.catalog_asset_id)
        return await original(candidate)

    monkeypatch.setattr(provider, "reference_characters", record)
    claimed = SimpleNamespace(
        identity=SimpleNamespace(
            generated_visual_prompt_version=OFFICIAL_ACCOUNT_GENERATED_VISUAL_PROMPT_V5_VERSION,
            visual_pipeline_version=OBSERVE_VISUAL_PIPELINE_VERSION,
        )
    )
    # These have no methods: even consulting a resume claim before all-five validation fails.
    unavailable = object()
    with pytest.raises(AppError, match="Xiaosai-only"):
        await execute_strict_visuals(
            repository=unavailable,
            claimed=claimed,
            article=unavailable,
            rendered=unavailable,
            references=candidates,
            catalog_candidates=candidates,
            catalog=provider,
            store=unavailable,
            generator=unavailable,
            auditor=unavailable,
        )
    assert checked == [candidate.catalog_asset_id for candidate in candidates]


async def test_missing_character_capability_and_existing_native_size_floor_fail(tmp_path):
    provider, _manifest, _entries, candidates = make_catalog(tmp_path, [("xiao-sai",)], size=320)
    assert await provider.reference_characters(candidates[0]) == ("xiao-sai",)
    with pytest.raises(AppError, match="Xiaosai-only"):
        await xiaosai_catalog_candidates(object(), candidates)
    with pytest.raises(ValueError, match="no eligible complete references"):
        await strict_catalog_candidates(provider, candidates)


async def test_real_worker_filters_selection_without_shrinking_copy_comparison_pool(monkeypatch):
    repository, _store, generator, auditor, executor = _components()
    repository.identity = replace(
        repository.identity, visual_pipeline_version=OBSERVE_VISUAL_PIPELINE_VERSION
    )
    catalog = executor._catalog_media_provider
    full = await catalog.load_candidates()
    only_xiaosai = full[0].catalog_asset_ref

    async def characters(candidate):
        return ("xiao-sai",) if candidate.catalog_asset_ref == only_xiaosai else ("sai-xiansheng",)

    monkeypatch.setattr(catalog, "reference_characters", characters)
    assert await executor.execute_next("independent-xiaosai-pool-check")
    assert repository.failure is None and repository.draft is not None
    assert len(generator.calls) == 5 and len(auditor.calls) == 6
    assert {call.references[0].asset_id for call in generator.calls} == {only_xiaosai}
    full_hashes = {candidate.sha256 for candidate in full}
    assert len(full_hashes) == 3
    assert all(
        set(row.subject.catalog_publication_sha256s) == full_hashes
        for row in repository.audits.values()
    )


async def test_resumed_article_cannot_reuse_reference_with_changed_character(monkeypatch):
    repository, _store, generator, auditor, executor = _components()
    original_generate = generator.generate

    async def interrupt_second(request):
        if len(generator.calls) == 1:
            raise asyncio.CancelledError
        return await original_generate(request)

    monkeypatch.setattr(generator, "generate", interrupt_second)
    with pytest.raises(asyncio.CancelledError):
        await executor.execute_next("xiaosai-interrupted")
    assert repository.article is not None and len(generator.calls) == 1 and not auditor.calls
    assert repository.generated[0].status == "ready"
    first_ref = repository.article.article.media_selection.assignments[0].candidate_ref

    async def changed_character(candidate):
        return ("sai-xiansheng",) if candidate.catalog_asset_ref == first_ref else ("xiao-sai",)

    monkeypatch.setattr(executor._catalog_media_provider, "reference_characters", changed_character)
    monkeypatch.setattr(generator, "generate", original_generate)
    repository.claimed = False
    assert await executor.execute_next("xiaosai-resume-after-metadata-drift")
    assert repository.failure is not None and repository.draft is None
    assert len(generator.calls) == 1 and not auditor.calls
    assert repository.generated[0].status == "ready"


async def test_historical_v4_does_not_call_new_character_capability(monkeypatch):
    repository, _store, generator, auditor, executor = _components()
    repository.identity = replace(
        repository.identity,
        generated_visual_prompt_version=OFFICIAL_ACCOUNT_GENERATED_VISUAL_PROMPT_V4_VERSION,
    )

    async def forbidden(_candidate):
        raise AssertionError("V4 must not inspect the new character capability")

    monkeypatch.setattr(executor._catalog_media_provider, "reference_characters", forbidden)
    assert await executor.execute_next("historical-v4-no-character-filter")
    assert repository.failure is None and repository.draft is not None
    assert len(generator.calls) == 5 and len(auditor.calls) == 6
