from __future__ import annotations

import base64
import json
import socket
from dataclasses import replace
from datetime import UTC, datetime
from hashlib import sha256
from io import BytesIO
from pathlib import Path
from random import Random
from typing import Any
from uuid import uuid4

import httpx
import pytest
from app.application.ports.image_generation import ImageGenerationRequest, ImageGenerationResult
from app.application.ports.image_validation import ImageQualityAuditRequest, ImageQualityAuditResult
from app.application.ports.official_account_local import (
    OfficialAccountGenerationRequest,
    OfficialAccountSourceMedia,
)
from app.application.services.official_account_visual_preview import (
    AUDIT_MODEL,
    INPUT_VERSION,
    SOURCE_RUN_ID,
    PreviewJournal,
    PreviewSnapshot,
    VisualPreviewError,
    canonical_json,
    execute_visual_preview,
    finalize_visual_preview,
    load_preview_input,
    plan_visual_preview,
    preview_audit_passes,
    preview_image_checks,
    rerender_visual_preview,
)
from app.domain.image_validation import ImageQualityAuditIssue
from app.domain.official_account_local import (
    ArticleMediaSelectionItem,
    ArticleMediaSelectionSnapshot,
    ArticleNewsContextMediaItem,
    ArticleNewsContextMediaSnapshot,
    OfficialAccountAuditVerdict,
    SemanticMediaCandidate,
    assign_deterministic_body_media_v4,
    build_article_package,
)
from app.infrastructure.official_account_local import (
    DeterministicFakeOfficialAccountArticleGenerator,
    fixture_source_snapshot,
)
from app.official_account_visual_preview_main import PreviewJournalTransport, main
from PIL import Image, ImageDraw
from pydantic import ValidationError
from test_official_account_article import identity
from test_official_account_news_context import _v10_versions


def _image(seed: int, size: tuple[int, int] = (512, 512), fmt: str = "JPEG") -> bytes:
    random = Random(seed)
    image = Image.new("RGB", size)
    draw = ImageDraw.Draw(image)
    for x in range(9):
        for y in range(8):
            draw.rectangle(
                (
                    x * size[0] // 9,
                    y * size[1] // 8,
                    (x + 1) * size[0] // 9,
                    (y + 1) * size[1] // 8,
                ),
                fill=tuple(random.randrange(256) for _ in range(3)),
            )
    output = BytesIO()
    image.save(output, format=fmt)
    return output.getvalue()


def _manifest(root: Path) -> str:
    entries = [
        {
            "path": path.relative_to(root).as_posix(),
            "sha256": sha256(path.read_bytes()).hexdigest(),
            "byte_size": path.stat().st_size,
        }
        for path in sorted(root.rglob("*"))
        if path.is_file() and path.name != "manifest.json"
    ]
    body = canonical_json(
        {
            "schema_version": INPUT_VERSION,
            "source_run_id": str(SOURCE_RUN_ID),
            "status": "ready",
            "files": entries,
        }
    )
    (root / "manifest.json").write_bytes(body)
    return sha256(body).hexdigest()


@pytest.fixture
async def captured(tmp_path: Path) -> tuple[Path, str]:
    root = tmp_path / "source"
    root.mkdir(mode=0o700)
    for name in ("catalog", "context", "references"):
        (root / name).mkdir()
    versions = _v10_versions()
    source = fixture_source_snapshot(multi_image=True, semantic_media=True)
    configured = replace(identity(), **versions.model_dump())
    generated = await DeterministicFakeOfficialAccountArticleGenerator().generate(
        OfficialAccountGenerationRequest(
            run_id=SOURCE_RUN_ID,
            source=source,
            identity=configured,
            request_fingerprint="a" * 64,
            max_output_tokens=8192,
        )
    )
    bodies = tuple(_image(index) for index in range(5))
    candidates = tuple(
        SemanticMediaCandidate(
            candidate_id=f"{index + 1:016x}",
            sha256=sha256(body).hexdigest(),
            semantic_label=f"Scene {index}",
            semantic_tags=("observation",),
            alt_text=f"Scene {index}",
            caption_text="Scientific observation",
            publication_priority=index,
        )
        for index, body in enumerate(bodies)
    )
    assignments = assign_deterministic_body_media_v4(
        sections=generated.draft.sections, candidates=candidates
    )
    catalog = tuple(
        OfficialAccountSourceMedia(
            source_image_artifact_id=None,
            fixture_id=f"catalog:{item.candidate_id}",
            media_type="image/jpeg",
            byte_size=len(bodies[index]),
            sha256=item.sha256,
            ordinal=index,
            assigned_section_index=item.section_index,
            catalog_asset_ref=item.candidate_id,
            catalog_asset_id=f"PRIVATE-CATALOG-SENTINEL-{index}",
            catalog_version="test-approved-catalog-v1",
            source_master_sha256=f"{index + 20:064x}",
            width=512,
            height=512,
            alt_text=f"Scene {index}",
        )
        for index, item in enumerate(assignments)
    )
    selected = ArticleMediaSelectionSnapshot(
        media_plan_version=versions.media_plan_version,
        visual_query_version=versions.visual_query_version,
        visual_selector_version=versions.visual_selector_version,
        status="semantic_unavailable",
        closed_reason="disabled",
        catalog_version="test-approved-catalog-v1",
        catalog_fingerprint="a" * 64,
        assignments=tuple(
            ArticleMediaSelectionItem(
                ordinal=index,
                section_index=item.assigned_section_index,
                candidate_ref=item.catalog_asset_ref,
                source_checksum=item.source_master_sha256,
                publication_checksum=item.sha256,
                selection_method="deterministic_tag",
                reason_code="stable_fallback",
            )
            for index, item in enumerate(catalog)
        ),
    )
    context_bytes = _image(40, (1004, 620), "PNG")
    original = ArticleNewsContextMediaItem(
        ordinal=0,
        section_index=2,
        source_article_image_id=uuid4(),
        sha256=sha256(context_bytes).hexdigest(),
        media_type="image/png",
        width=1004,
        height=620,
        alt_text=generated.draft.sections[2].heading,
        caption="Original source image",
        credit="Source",
        source_page_url=source.evidence[0].source_url,
        rights_status="publish_permission_unverified",
    )
    article = build_article_package(
        draft=generated.draft,
        source=source,
        versions=versions,
        default_author=configured.default_author,
        body_media_candidate_count=5,
        semantic_media_assignments=assignments,
        media_selection=selected,
        news_context_media=ArticleNewsContextMediaSnapshot(
            selection_version=versions.context_media_plan_version,
            status="partial",
            items=(original,),
        ),
    )
    context = OfficialAccountSourceMedia(
        source_image_artifact_id=None,
        fixture_id=None,
        media_type="image/png",
        byte_size=len(context_bytes),
        sha256=original.sha256,
        source_article_image_id=original.source_article_image_id,
        assigned_section_index=2,
        alt_text=original.alt_text,
        caption_text=original.caption or "",
        credit=original.credit,
        source_page_url=original.source_page_url,
        rights_status=original.rights_status,
        width=1004,
        height=620,
        context_only_not_evidence=True,
    )
    # Include a low resolution original in the reference set: it must never be selected.
    low = _image(8, (281, 276))
    references = (
        replace(
            catalog[0], byte_size=len(low), sha256=sha256(low).hexdigest(), width=281, height=276
        ),
        catalog[1],
    )
    snapshot = PreviewSnapshot(
        article_version_id=uuid4(),
        render_version_id=uuid4(),
        render_fingerprint="c" * 64,
        article_created_at=datetime.now(UTC),
        validation_issues=(),
        audit=OfficialAccountAuditVerdict(accepted=True),
        catalog_media=catalog,
        context_media=context,
        references=references,
    )
    (root / "article.json").write_bytes(article.model_dump_json().encode())
    (root / "source.json").write_bytes(source.model_dump_json().encode())
    (root / "snapshot.json").write_bytes(snapshot.model_dump_json().encode())
    for index, body in enumerate(bodies):
        (root / f"catalog/{index}.jpg").write_bytes(body)
    (root / "context/0.png").write_bytes(context_bytes)
    (root / "references/0.jpg").write_bytes(low)
    (root / "references/1.jpg").write_bytes(bodies[1])
    return root, _manifest(root)


class _Generator:
    def __init__(self, journal: PreviewJournal, fail_at: int | None = None) -> None:
        self.journal = journal
        self.requests: list[ImageGenerationRequest] = []
        self.fail_at = fail_at

    async def generate(self, request: ImageGenerationRequest) -> ImageGenerationResult:
        ordinal = len(self.requests)
        assert (self.journal.root / f"calls/generation-{ordinal}.intent.json").is_file()
        self.requests.append(request)
        if ordinal == self.fail_at:
            raise RuntimeError("PRIVATE-PROVIDER-RESPONSE-SENTINEL")
        body = _image(ordinal + 100, (1536, 1024), "PNG")
        return ImageGenerationResult(
            provider="comfly",
            model="gpt-image-2",
            request_fingerprint=request.request_fingerprint,
            provider_task_id="PRIVATE-TASK-SENTINEL",
            provider_upload_id=None,
            image_bytes=body,
            media_type="image/png",
            width=1536,
            height=1024,
            attempts=1,
        )


class _Auditor:
    def __init__(
        self, journal: PreviewJournal, *, warning: bool = False, unavailable: bool = False
    ) -> None:
        self.journal = journal
        self.requests: list[ImageQualityAuditRequest] = []
        self.warning = warning
        self.unavailable = unavailable

    async def audit(self, request: ImageQualityAuditRequest) -> ImageQualityAuditResult:
        assert (self.journal.root / f"calls/audit-{len(self.requests)}.intent.json").is_file()
        self.requests.append(request)
        if self.unavailable:
            raise RuntimeError("PRIVATE-AUDIT-SENTINEL")
        return ImageQualityAuditResult(
            accepted=True,
            provider="openai-compatible",
            model=AUDIT_MODEL,
            request_fingerprint=request.request_fingerprint,
            issues=(ImageQualityAuditIssue(code="layout_quality", severity="warning"),)
            if self.warning
            else (),
        )


async def _execute(captured: tuple[Path, str], tmp_path: Path, **kwargs: Any):
    root, digest = captured
    plan = plan_visual_preview(load_preview_input(root, manifest_sha256=digest))
    journal = PreviewJournal(tmp_path / "preview", plan)
    generator = _Generator(journal)
    auditor = _Auditor(journal, **kwargs)
    manifest = await execute_visual_preview(
        plan=plan, journal=journal, generator=generator, auditor=auditor
    )
    return plan, journal, generator, auditor, manifest


def test_default_preflight_no_network_or_settings(captured, monkeypatch, capsys):
    def forbidden(*args, **kwargs):
        raise AssertionError("Network must not be used")

    monkeypatch.setattr(socket, "socket", forbidden)
    monkeypatch.setenv("IMAGE_PROVIDER_MODE", "invalid-sentinel")
    root, digest = captured
    assert main(["--source-dir", str(root), "--source-manifest-sha256", digest]) == 0
    assert json.loads(capsys.readouterr().out)["provider_calls"] == 0


@pytest.mark.parametrize(
    "member", ["article.json", "source.json", "context/0.png", "references/1.jpg"]
)
def test_hash_drift_blocks_before_clients(captured, member):
    root, digest = captured
    (root / member).write_bytes((root / member).read_bytes() + b"tamper")
    with pytest.raises(VisualPreviewError):
        load_preview_input(root, manifest_sha256=digest)


@pytest.mark.parametrize(
    "field", ["assigned_section_index", "source_article_image_id", "rights_status", "width"]
)
def test_rechecks_context_binding_even_with_updated_bundle_hash(captured, field):
    root, _digest = captured
    path = root / "snapshot.json"
    data = json.loads(path.read_bytes())
    data["context_media"][field] = {
        "assigned_section_index": 4,
        "source_article_image_id": str(uuid4()),
        "rights_status": "licensed",
        "width": 1005,
    }[field]
    path.write_bytes(canonical_json(data))
    with pytest.raises(VisualPreviewError):
        load_preview_input(root, manifest_sha256=_manifest(root))


def test_output_rejected_before_settings_and_secret_inspection(
    captured, tmp_path, monkeypatch, capsys
):
    from app import official_account_visual_preview_main as cli
    from app.core import config

    settings_calls = []

    def forbidden(*args, **kwargs):
        settings_calls.append(True)
        raise AssertionError("Credentials/settings must not be inspected")

    root, digest = captured
    monkeypatch.setattr(config, "Settings", forbidden)
    output = tmp_path / "exists"
    output.mkdir()
    assert (
        cli.main(
            [
                "--source-dir",
                str(root),
                "--source-manifest-sha256",
                digest,
                "--live",
                "--output-dir",
                str(output),
            ]
        )
        == 1
    )
    assert not list(output.iterdir())
    assert settings_calls == []
    assert "Credentials/settings" not in capsys.readouterr().out


@pytest.mark.parametrize(
    "mutation", ["duplicate", "extra", "traversal", "symlink", "oversized", "directory_symlink"]
)
def test_bundle_rejects_unsafe_members(captured, tmp_path, mutation):
    root, digest = captured
    if mutation == "duplicate":
        path = root / "snapshot.json"
        path.write_bytes(path.read_bytes().replace(b"{", b'{"article_version_id":"ignored",', 1))
        digest = _manifest(root)
    elif mutation == "extra":
        (root / "undeclared").write_text("private")
    elif mutation == "traversal":
        value = json.loads((root / "manifest.json").read_bytes())
        value["files"][0]["path"] = "../article.json"
        (root / "manifest.json").write_bytes(canonical_json(value))
        digest = sha256((root / "manifest.json").read_bytes()).hexdigest()
    elif mutation == "symlink":
        target = root / "article.json"
        private = tmp_path / "moved-article.json"
        target.rename(private)
        target.symlink_to(private)
    elif mutation == "directory_symlink":
        moved = tmp_path / "moved-references"
        (root / "references").rename(moved)
        (root / "references").symlink_to(moved, target_is_directory=True)
    else:
        with (root / "source.json").open("wb") as stream:
            stream.truncate(2 * 1024 * 1024)
    with pytest.raises((VisualPreviewError, ValidationError)):
        load_preview_input(root, manifest_sha256=digest)


async def test_complete_preview_preserves_source_audits_final_bytes_and_truth(captured, tmp_path):
    plan, journal, generator, auditor, manifest = await _execute(captured, tmp_path)
    assert len(generator.requests) == 5 and len(auditor.requests) == 6
    assert all(request.output_size == "1536x1024" for request in generator.requests)
    assert len({scene.plan.block_fingerprint for scene in plan.scenes}) == 5
    assert all(scene.reference.width == 512 for scene in plan.scenes)
    assert all(scene.reference.selection_method == "deterministic_tag" for scene in plan.scenes)
    assert manifest["quality_gate_passed"] is True
    assert manifest["preview_accepted"] is False and manifest["database_persisted"] is False
    assert (journal.root / "article.json").read_bytes() == (
        captured[0] / "article.json"
    ).read_bytes()
    assert (journal.root / "source.json").read_bytes() == (captured[0] / "source.json").read_bytes()
    assert (journal.root / "assets/context-00.png").read_bytes() == (
        captured[0] / "context/0.png"
    ).read_bytes()
    for index, request in enumerate(auditor.requests):
        path = f"assets/body-{index:02d}.jpg" if index < 5 else "assets/cover-wide.jpg"
        assert request.image_bytes == (journal.root / path).read_bytes()
        assert request.references[0].image_bytes.startswith(b"\x89PNG")
        assert len(request.criteria) == 8 and all(len(value) <= 200 for value in request.criteria)
    exported_json = b"".join(path.read_bytes() for path in journal.root.rglob("*.json"))
    assert b"PRIVATE-CATALOG-SENTINEL" not in exported_json
    assert b"PRIVATE-TASK-SENTINEL" not in exported_json
    assert generator.requests[0].prompt.encode() not in exported_json
    before = {path: path.read_bytes() for path in journal.root.rglob("*") if path.is_file()}
    with pytest.raises(VisualPreviewError, match="preview_output_exists"):
        PreviewJournal(journal.root, plan)
    assert before == {path: path.read_bytes() for path in before}


async def test_unknown_generation_preserves_paid_siblings_and_cannot_restart(captured, tmp_path):
    plan = plan_visual_preview(load_preview_input(captured[0], manifest_sha256=captured[1]))
    journal = PreviewJournal(tmp_path / "incomplete", plan)
    generator = _Generator(journal, fail_at=2)
    with pytest.raises(VisualPreviewError, match="preview_incomplete"):
        await execute_visual_preview(
            plan=plan, journal=journal, generator=generator, auditor=_Auditor(journal)
        )
    assert len(generator.requests) == 3
    assert len(list((journal.root / "assets").glob("body-*.jpg"))) == 2
    assert (
        json.loads((journal.root / "calls/generation-2.result.json").read_bytes())["status"]
        == "failed_or_unknown"
    )
    assert b"PRIVATE-PROVIDER-RESPONSE-SENTINEL" not in b"".join(
        path.read_bytes() for path in journal.root.rglob("*.json")
    )
    with pytest.raises(VisualPreviewError, match="preview_output_exists"):
        PreviewJournal(journal.root, plan)


@pytest.mark.parametrize("kwargs", [{"warning": True}, {"unavailable": True}])
async def test_nonaccepted_audits_keep_complete_visuals_but_block_quality(
    captured, tmp_path, kwargs
):
    _, journal, generator, auditor, manifest = await _execute(captured, tmp_path, **kwargs)
    assert len(generator.requests) == 5 and len(auditor.requests) == 6
    assert manifest["quality_gate_passed"] is False
    assert (journal.root / "preview.html").exists()


def test_gate_rejects_missing_warning_rejected_and_model_mismatch():
    base = ImageQualityAuditResult(
        accepted=True, provider="openai-compatible", model=AUDIT_MODEL, request_fingerprint="f" * 64
    )
    assert preview_audit_passes(base, request_fingerprint="f" * 64)
    for result in (
        None,
        replace(base, accepted=False),
        replace(base, model="glm-5.2"),
        replace(base, request_fingerprint="e" * 64),
        replace(base, issues=(ImageQualityAuditIssue(code="layout_quality", severity="warning"),)),
    ):
        assert not preview_audit_passes(result, request_fingerprint="f" * 64)


def test_deterministic_gate_rejects_catalog_low_resolution_exact_and_perceptual_repetition():
    body = _image(6, (1536, 1024))
    codes = preview_image_checks((body,) * 5, catalog_images=(body,))
    assert {
        "preview_catalog_reuse",
        "preview_exact_repetition",
        "preview_perceptual_repetition",
    } <= set(codes)
    assert "preview_body_resolution_invalid" in preview_image_checks(
        (_image(7),) * 5, catalog_images=()
    )


async def test_transport_intent_before_dispatch_caps_and_unknown_privacy(captured, tmp_path):
    plan = plan_visual_preview(load_preview_input(captured[0], manifest_sha256=captured[1]))
    journal = PreviewJournal(tmp_path / "transport-preview", plan)
    dispatched = 0

    async def handler(request):
        nonlocal dispatched
        assert (journal.root / "transport/generation-000.intent.json").exists()
        dispatched += 1
        raise httpx.ReadTimeout("SECRET-ENDPOINT-SENTINEL")

    transport = PreviewJournalTransport(
        journal=journal,
        inner=httpx.MockTransport(handler),
        kind="generation",
        base_url="https://generation.example",
    )
    async with httpx.AsyncClient(transport=transport) as client:
        with pytest.raises(VisualPreviewError, match="without_intent"):
            await client.post("https://generation.example/v1/images/generations")
        journal.begin_call("generation", 0, {"request_fingerprint": "a" * 64})
        with pytest.raises(httpx.ReadTimeout):
            await client.post("https://generation.example/v1/images/generations")
        with pytest.raises(VisualPreviewError, match="budget_exceeded"):
            await client.post("https://generation.example/v1/images/generations")
    assert dispatched == 1
    records = b"".join(path.read_bytes() for path in (journal.root / "transport").iterdir())
    assert b"SECRET-ENDPOINT-SENTINEL" not in records
    assert b"generation.example" not in records


async def test_live_composition_one_shot_adapters_exact_models_and_final_bytes(
    captured, tmp_path, monkeypatch
):
    from app import official_account_visual_preview_main as cli
    from app.core import config

    settings_values = dict(
        image_provider_mode="comfly",
        image_model="gpt-image-2",
        comfly_base_url="https://ai.comfly.org",
        comfly_api_key="test-generation-key",
        ai_provider_mode="zhipu",
        ai_platform_base_url="https://open.bigmodel.cn/api/paas/v4",
        ai_platform_api_key="test-audit-key",
        ai_chat_model="text-model-must-not-be-used",
        image_quality_audit_model="configured-model-must-not-override-approved-preview",
        image_max_attempts=3,
        ai_max_attempts=3,
    )
    settings = config.Settings(_env_file=None, **settings_values)
    for name, value in settings_values.items():
        monkeypatch.setenv(name.upper(), str(value))
    output = tmp_path / "composed-preview"
    generation_calls = 0
    audit_calls = 0
    transport_constructions = []

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal generation_calls, audit_calls
        payload = json.loads(request.content)
        assert request.method == "POST"
        if request.url.host == "ai.comfly.org":
            ordinal = generation_calls
            assert request.url.path == "/v1/images/generations"
            assert request.headers["authorization"] == "Bearer test-generation-key"
            assert payload["model"] == "gpt-image-2"
            assert payload["size"] == "1536x1024"
            assert (output / f"calls/generation-{ordinal}.intent.json").is_file()
            assert (output / f"transport/generation-{ordinal:03d}.intent.json").is_file()
            generation_calls += 1
            return httpx.Response(
                200,
                content=_image(ordinal + 100, (1536, 1024), "PNG"),
                headers={"content-type": "image/png"},
            )
        assert request.url == "https://open.bigmodel.cn/api/paas/v4/chat/completions"
        assert request.headers["authorization"] == "Bearer test-audit-key"
        assert payload["model"] == AUDIT_MODEL
        assert set(payload) == {"model", "messages", "max_tokens", "thinking", "do_sample"}
        assert payload["thinking"] == {"type": "disabled"}
        assert payload["do_sample"] is False
        ordinal = audit_calls
        assert (output / f"calls/audit-{ordinal}.intent.json").is_file()
        assert (output / f"transport/audit-{ordinal:03d}.intent.json").is_file()
        parts = payload["messages"][1]["content"]
        assert len(parts) == 3
        prefix, encoded = parts[1]["image_url"]["url"].split(",", 1)
        assert prefix == "data:image/jpeg;base64"
        path = f"assets/body-{ordinal:02d}.jpg" if ordinal < 5 else "assets/cover-wide.jpg"
        assert base64.b64decode(encoded, validate=True) == (output / path).read_bytes()
        assert parts[2]["image_url"]["url"].startswith("data:image/png;base64,")
        audit_calls += 1
        return httpx.Response(
            200,
            json={
                "model": AUDIT_MODEL,
                "choices": [{"message": {"content": '{"accepted":true,"issues":[]}'}}],
            },
        )

    def fake_transport(**kwargs):
        transport_constructions.append(kwargs)
        return httpx.MockTransport(handler)

    monkeypatch.setattr(httpx, "AsyncHTTPTransport", fake_transport)
    dotenv_root = tmp_path / "ambient-dotenv"
    dotenv_root.mkdir()
    (dotenv_root / ".env").write_text("APP_ENV=invalid-dotenv-sentinel\n")
    monkeypatch.chdir(dotenv_root)
    plan = plan_visual_preview(load_preview_input(captured[0], manifest_sha256=captured[1]))
    manifest = await cli._live(plan, output_dir=output)
    assert transport_constructions == [{"retries": 0, "trust_env": False}] * 2
    assert generation_calls == 5 and audit_calls == 6
    assert manifest["quality_gate_passed"] is True
    assert manifest["production_activated"] is False
    assert settings.image_max_attempts == 3 and settings.ai_max_attempts == 3
    with pytest.raises(VisualPreviewError, match="preview_output_exists"):
        await cli._live(plan, output_dir=output)
    assert generation_calls == 5 and audit_calls == 6
    for path in (output / "transport").glob("*.result.json"):
        assert json.loads(path.read_bytes())["status"] == "response_complete"


async def test_rerender_and_exact_mobile_finalization_make_no_provider_calls(captured, tmp_path):
    _, journal, generator, auditor, manifest = await _execute(captured, tmp_path)
    manifest_sha = sha256((journal.root / "manifest.json").read_bytes()).hexdigest()
    rebuilt = tmp_path / "rerender"
    new = rerender_visual_preview(
        source_dir=journal.root, manifest_sha256=manifest_sha, output_dir=rebuilt
    )
    assert new["content_fingerprint"] == manifest["content_fingerprint"]
    assert (rebuilt / "assets/body-00.jpg").read_bytes() == (
        journal.root / "assets/body-00.jpg"
    ).read_bytes()
    assert (rebuilt / "intent.json").read_bytes() == (journal.root / "intent.json").read_bytes()
    report = {
        "schema_version": "visual-preview-mobile-report-v1",
        **{
            key: manifest[key]
            for key in (
                "content_fingerprint",
                "body_sha256",
                "preview_sha256",
                "media_sha256_by_path",
            )
        },
        "observations": [
            {
                "width": width,
                "loaded_images": 7,
                "failed_images": 0,
                "horizontal_overflow_px": 0,
                "external_requests": 0,
                "copy_root_matches_body": True,
            }
            for width in (320, 430)
        ],
    }
    report_path = tmp_path / "browser.json"
    report_path.write_bytes(canonical_json({**report, "body_sha256": "e" * 64}))
    with pytest.raises(VisualPreviewError, match="mobile_binding_invalid"):
        finalize_visual_preview(
            root=journal.root, manifest_sha256=manifest_sha, report_path=report_path
        )
    report_path.write_bytes(canonical_json(report))
    result = finalize_visual_preview(
        root=journal.root, manifest_sha256=manifest_sha, report_path=report_path
    )
    assert result["preview_accepted"] is True and result["human_approved"] is False
    assert len(generator.requests) == 5 and len(auditor.requests) == 6
    with pytest.raises(FileExistsError):
        finalize_visual_preview(
            root=journal.root, manifest_sha256=manifest_sha, report_path=report_path
        )
    (journal.root / "assets/body-00.jpg").write_bytes(b"tamper")
    with pytest.raises(VisualPreviewError, match="artifact_changed"):
        rerender_visual_preview(
            source_dir=journal.root, manifest_sha256=manifest_sha, output_dir=tmp_path / "bad"
        )


@pytest.mark.parametrize("change", ["new_call", "intent_drift", "nested_directory"])
async def test_rerender_rejects_changed_paid_evidence_before_writing(captured, tmp_path, change):
    _, journal, _, _, _ = await _execute(captured, tmp_path)
    manifest_sha = sha256((journal.root / "manifest.json").read_bytes()).hexdigest()
    if change == "new_call":
        (journal.root / "calls/generation-5.intent.json").write_text("{}")
    elif change == "intent_drift":
        (journal.root / "intent.json").write_text("{}")
    else:
        (journal.root / "calls/hidden").mkdir()
    output = tmp_path / "must-not-create"
    with pytest.raises(VisualPreviewError):
        rerender_visual_preview(
            source_dir=journal.root, manifest_sha256=manifest_sha, output_dir=output
        )
    assert not output.exists()
