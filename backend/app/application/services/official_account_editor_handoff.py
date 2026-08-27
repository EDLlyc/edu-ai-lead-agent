"""Read-only local WeChat editor handoff projection and deterministic archive builder."""

# ruff: noqa: RUF001 -- Full-width Chinese punctuation is intentional UI/export copy.

from __future__ import annotations

import base64
import io
import json
from collections.abc import Mapping
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path, PurePosixPath
from types import MappingProxyType
from typing import Literal, cast
from uuid import UUID
from zipfile import ZIP_DEFLATED, ZipFile, ZipInfo

from PIL import Image, UnidentifiedImageError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.application.ports.official_account_local import (
    OfficialAccountMediaResult,
    StoredOfficialAccountManualReview,
)
from app.application.services.official_account_local import manual_review_request_fingerprint
from app.core.errors import AppError
from app.domain.official_account_editor_handoff import (
    EditorHandoffCheck,
    EditorHandoffIdentity,
    EditorHandoffMediaAsset,
    EditorHandoffPreflight,
    canonical_theme_projection,
    handoff_fingerprint,
    media_asset_path,
    render_editor_handoff_body,
    run_editor_handoff_preflight,
)
from app.domain.official_account_local import (
    ArticleImageBlock,
    ArticlePackage,
    article_package_fingerprint,
    article_version_bundle_kind,
    fingerprint,
    render_wechat_html,
)
from app.infrastructure.db.models import OfficialAccountLocalMediaModel
from app.infrastructure.db.official_account_local import PostgresOfficialAccountRepository
from app.infrastructure.official_account_media import (
    OfficialAccountLocalMediaResolver,
    OfficialAccountMediaIntegrityError,
    OfficialAccountPersistedMedia,
    persisted_media_snapshot,
)

PREVIEW_SCRIPT = """const button=document.getElementById('copy-button');
const status=document.getElementById('copy-status');
button.addEventListener('click',async()=>{
  const root=document.getElementById('copy-root');
  try{
    if(navigator.clipboard&&window.ClipboardItem){
      const html=new Blob([root.innerHTML],{type:'text/html'});
      const text=new Blob([root.innerText],{type:'text/plain'});
      await navigator.clipboard.write([new ClipboardItem({'text/html':html,'text/plain':text})]);
    }else{
      const range=document.createRange();range.selectNodeContents(root);
      const selection=window.getSelection();selection.removeAllRanges();selection.addRange(range);
      if(!document.execCommand('copy'))throw new Error('copy unavailable');
      selection.removeAllRanges();
    }
    status.textContent='正文已复制，可粘贴到微信公众号编辑器。';
  }catch(_error){status.textContent='复制失败，请使用正文文件手工复制。';}
});"""
PREVIEW_SCRIPT_CSP_HASH = base64.b64encode(sha256(PREVIEW_SCRIPT.encode("utf-8")).digest()).decode(
    "ascii"
)


@dataclass(frozen=True, slots=True)
class EditorHandoffArtifact:
    run_id: UUID
    fingerprint: str
    identity: EditorHandoffIdentity
    preflight: EditorHandoffPreflight
    media: tuple[EditorHandoffMediaAsset, ...]
    files: Mapping[str, bytes]
    zip_bytes: bytes
    zip_sha256: str
    bundle_filename: str

    @property
    def body_html(self) -> bytes:
        return self.files["article-body.html"]

    @property
    def preview_html(self) -> bytes:
        return self.files["preview.html"]


@dataclass(frozen=True, slots=True)
class EditorHandoffInspection:
    run_id: UUID
    state: Literal["blocked", "ready"]
    checks: tuple[EditorHandoffCheck, ...]
    artifact: EditorHandoffArtifact | None

    @property
    def blocking_codes(self) -> tuple[str, ...]:
        return tuple(
            item.code for item in self.checks if item.severity == "error" and not item.passed
        )

    @property
    def warning_codes(self) -> tuple[str, ...]:
        return tuple(
            item.code for item in self.checks if item.severity == "warning" and not item.passed
        )


class OfficialAccountEditorHandoffService:
    """Build an immutable in-memory handoff from already durable approved state."""

    def __init__(
        self,
        *,
        session_factory: async_sessionmaker[AsyncSession],
        resolver: OfficialAccountLocalMediaResolver,
    ) -> None:
        self._session_factory = session_factory
        self._repository = PostgresOfficialAccountRepository(session_factory)
        self._resolver = resolver

    async def inspect(self, run_id: UUID) -> EditorHandoffInspection:
        run = await self._repository.get_run(run_id)
        initial_checks: list[EditorHandoffCheck] = []

        def gate(code: str, passed: bool, field: str, detail: str) -> None:
            initial_checks.append(
                EditorHandoffCheck(
                    code=code,
                    severity="info" if passed else "error",
                    passed=passed,
                    field=field,
                    detail=detail,
                )
            )

        gate(
            "run_ready",
            run.status == "ready",
            "run.status",
            "运行状态必须为 ready",
        )
        article = await self._repository.get_article(run_id)
        gate("article_present", article is not None, "article", "结构化文章必须存在")
        article_version_supported = False
        if article is not None:
            article_version_supported = (
                article_version_bundle_kind(article.article.versions) is not None
            )
            gate(
                "article_version_supported",
                article_version_supported,
                "article.versions",
                "文章版本身份必须可重放",
            )
            gate(
                "article_fingerprint_valid",
                article.article.content_fingerprint == article_package_fingerprint(article.article),
                "article.content_fingerprint",
                "文章内容指纹必须匹配",
            )
            gate(
                "deterministic_validation_passed",
                article.validation_passed,
                "article.validation",
                "确定性文章校验必须通过",
            )
            gate(
                "model_audit_accepted",
                article.audit is not None and article.audit.accepted,
                "article.audit",
                "模型审校必须接受文章",
            )
        draft = await self._repository.get_draft(run_id)
        render = await self._repository.get_render(run_id)
        gate("render_present", render is not None, "render", "已批准文章的固定渲染必须存在")
        if article is not None and render is not None and article_version_supported:
            gate(
                "render_article_lineage_valid",
                render.article_version_id == article.id,
                "render.article_version_id",
                "固定渲染必须属于当前结构化文章版本",
            )
            try:
                expected_render = render_wechat_html(article.article)
            except ValueError:
                render_fingerprint_valid = False
            else:
                render_fingerprint_valid = (
                    render.canonical_html == expected_render.canonical_html
                    and render.render_fingerprint == expected_render.render_fingerprint
                )
            gate(
                "render_fingerprint_valid",
                render_fingerprint_valid,
                "render.render_fingerprint",
                "固定渲染正文和指纹必须匹配文章版本身份",
            )
        draft_ready = bool(
            draft is not None
            and getattr(draft, "state", None) == "ready"
            and getattr(draft, "simulation", None) is True
        )
        gate(
            "simulated_draft_ready",
            draft_ready,
            "draft",
            "本地模拟草稿必须就绪",
        )
        if draft is not None and render is not None:
            gate(
                "draft_fingerprint_valid",
                draft.resolved_fingerprint
                == fingerprint(
                    render.render_fingerprint,
                    draft.request_fingerprint,
                    draft.resolved_html,
                ),
                "draft.resolved_fingerprint",
                "本地草稿必须匹配不可变渲染谱系",
            )
        review = await self._repository.get_manual_review(run_id)
        review_code = (
            "immutable_review_approved"
            if review is not None and review.decision == "approved"
            else "immutable_review_rejected"
            if review is not None
            else "immutable_review_pending"
        )
        gate(
            review_code,
            review is not None and review.decision == "approved",
            "manual_review",
            "必须存在不可变的批准审稿记录",
        )
        if review is not None:
            gate(
                "review_fingerprint_valid",
                review.request_fingerprint
                == manual_review_request_fingerprint(
                    run_id=run_id,
                    decision=review.decision,
                    reviewer_label=review.reviewer_label,
                    note=review.note,
                ),
                "manual_review.request_fingerprint",
                "人工审稿指纹必须匹配不可变审稿输入",
            )
        if any(item.severity == "error" and not item.passed for item in initial_checks):
            return EditorHandoffInspection(
                run_id=run_id,
                state="blocked",
                checks=tuple(initial_checks),
                artifact=None,
            )
        if article is None or draft is None or review is None:  # narrowed by the gates above
            raise RuntimeError("editor handoff gate narrowing failed")

        try:
            media_rows = await self._load_media_rows(run_id)
            verified = await self._resolve_media(media_rows)
            artifact = _build_artifact(
                run_id=run_id,
                run_request_fingerprint=run.request_fingerprint,
                article=article.article,
                review=review,
                draft_resolved_fingerprint=draft.resolved_fingerprint,
                media=verified,
                eligibility_checks=tuple(initial_checks),
            )
        except (
            KeyError,
            OfficialAccountMediaIntegrityError,
            RuntimeError,
            UnidentifiedImageError,
            ValueError,
        ):
            failed = EditorHandoffCheck(
                code="handoff_integrity_failed",
                severity="error",
                passed=False,
                field="handoff",
                detail="媒体、正文或交接包完整性校验失败",
            )
            return EditorHandoffInspection(
                run_id=run_id,
                state="blocked",
                checks=tuple([*initial_checks, failed]),
                artifact=None,
            )
        return EditorHandoffInspection(
            run_id=run_id,
            state="ready",
            checks=artifact.preflight.checks,
            artifact=artifact,
        )

    async def require_artifact(self, run_id: UUID) -> EditorHandoffArtifact:
        inspection = await self.inspect(run_id)
        if inspection.artifact is None:
            code = inspection.blocking_codes[0] if inspection.blocking_codes else "handoff_blocked"
            raise AppError(code, "official-account editor handoff is blocked", 409)
        return inspection.artifact

    async def _load_media_rows(
        self, run_id: UUID
    ) -> tuple[tuple[OfficialAccountPersistedMedia, OfficialAccountMediaResult], ...]:
        async with self._session_factory() as session:
            rows = tuple(
                (
                    await session.scalars(
                        select(OfficialAccountLocalMediaModel)
                        .where(
                            OfficialAccountLocalMediaModel.run_id == run_id,
                            OfficialAccountLocalMediaModel.status == "ready",
                        )
                        .order_by(
                            OfficialAccountLocalMediaModel.role,
                            OfficialAccountLocalMediaModel.ordinal,
                        )
                    )
                ).all()
            )
        results = await self._repository.list_media(run_id)
        by_identity = {(item.role, item.ordinal): item for _row_id, item in results}
        return tuple(
            (
                persisted_media_snapshot(row),
                by_identity[(cast(Literal["body", "cover", "context"], row.role), row.ordinal)],
            )
            for row in rows
        )

    async def _resolve_media(
        self,
        rows: tuple[tuple[OfficialAccountPersistedMedia, OfficialAccountMediaResult], ...],
    ) -> tuple[tuple[OfficialAccountMediaResult, bytes], ...]:
        verified: list[tuple[OfficialAccountMediaResult, bytes]] = []
        for snapshot, result in rows:
            async with self._session_factory() as session:
                body = await self._resolver.read_verified_bytes(session=session, media=snapshot)
            if len(body) != result.byte_size or sha256(body).hexdigest() != result.sha256:
                raise OfficialAccountMediaIntegrityError("editor handoff media bytes changed")
            verified.append((result, body))
        return tuple(verified)


def _build_artifact(
    *,
    run_id: UUID,
    run_request_fingerprint: str,
    article: ArticlePackage,
    review: StoredOfficialAccountManualReview,
    draft_resolved_fingerprint: str,
    media: tuple[tuple[OfficialAccountMediaResult, bytes], ...],
    eligibility_checks: tuple[EditorHandoffCheck, ...],
) -> EditorHandoffArtifact:
    identity = EditorHandoffIdentity()
    media_assets, asset_bodies = _build_media_assets(article=article, media=media)
    rendered = render_editor_handoff_body(article=article, media=media_assets)
    preview = _preview_document(rendered.body_html)
    preflight = run_editor_handoff_preflight(
        body_html=rendered.body_html,
        preview_html=preview,
        media=media_assets,
        approved=True,
        extra_checks=eligibility_checks,
    )
    if not preflight.passed:
        raise ValueError("editor handoff preflight failed")
    fingerprint = handoff_fingerprint(
        identity.model_dump(mode="json"),
        run_id,
        run_request_fingerprint,
        article.content_fingerprint,
        review.request_fingerprint,
        draft_resolved_fingerprint,
        rendered.body_sha256,
        tuple((item.path, item.sha256, item.byte_size) for item in media_assets),
    )
    files: dict[str, bytes] = {
        "article-body.html": rendered.body_html.encode("utf-8"),
        "preview.html": preview.encode("utf-8"),
        "article.md": _article_markdown(article, media_assets).encode("utf-8"),
        "article.json": _json_bytes(_safe_article_projection(article)),
        "sources.json": _json_bytes(_sources_projection(article)),
        "rights.json": _json_bytes(_rights_projection(media_assets)),
        "review.json": _json_bytes(_review_projection(review)),
        "preflight.json": _json_bytes(preflight.model_dump(mode="json")),
        "mobile-validation.json": _json_bytes(
            {"status": "not_run", "viewports": [320, 430], "external_requests": None}
        ),
        "theme.json": _json_bytes(canonical_theme_projection()),
        "README.md": _readme(run_id, fingerprint, preflight).encode("utf-8"),
        **asset_bodies,
    }
    manifest_files = [_file_projection(path, body) for path, body in sorted(files.items())]
    manifest = {
        "bundle_version": identity.bundle_version,
        "fingerprint": fingerprint,
        "run_id": str(run_id),
        "simulation": True,
        "local_only": True,
        "copy_ready": True,
        "published": False,
        "identity": identity.model_dump(mode="json"),
        "lineage": {
            "run_request_fingerprint": run_request_fingerprint,
            "article_content_fingerprint": article.content_fingerprint,
            "manual_review_fingerprint": review.request_fingerprint,
            "draft_resolved_fingerprint": draft_resolved_fingerprint,
            "body_sha256": rendered.body_sha256,
        },
        "media": [item.model_dump(mode="json") for item in media_assets],
        "files": manifest_files,
        "archive": {
            "timestamp": "1980-01-01T00:00:00Z",
            "mode": "0644",
            "compression": "deflate-9",
        },
    }
    files["manifest.json"] = _json_bytes(manifest)
    archive_root = f"wechat-editor-handoff-{fingerprint[:16]}"
    zip_bytes = _deterministic_zip(files, archive_root=archive_root)
    _verify_zip(zip_bytes, files=files, archive_root=archive_root)
    return EditorHandoffArtifact(
        run_id=run_id,
        fingerprint=fingerprint,
        identity=identity,
        preflight=preflight,
        media=media_assets,
        files=MappingProxyType(files),
        zip_bytes=zip_bytes,
        zip_sha256=sha256(zip_bytes).hexdigest(),
        bundle_filename=f"{archive_root}.zip",
    )


def write_editor_handoff_artifact(artifact: EditorHandoffArtifact, output_root: Path) -> Path:
    """Write one verified local fixture artifact without overwriting a different export."""
    root = output_root.expanduser().resolve()
    if root == Path(root.anchor):
        raise ValueError("editor handoff output cannot be a filesystem root")
    target = root / f"wechat-editor-handoff-{artifact.fingerprint[:16]}"
    target.mkdir(parents=True, exist_ok=True)
    for relative, body in artifact.files.items():
        safe = _safe_path(relative)
        path = target / safe
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.exists() and path.read_bytes() != body:
            raise FileExistsError("editor handoff output contains different bytes")
        path.write_bytes(body)
    zip_path = target / artifact.bundle_filename
    if zip_path.exists() and zip_path.read_bytes() != artifact.zip_bytes:
        raise FileExistsError("editor handoff ZIP contains different bytes")
    zip_path.write_bytes(artifact.zip_bytes)
    return target


def _build_media_assets(
    *,
    article: ArticlePackage,
    media: tuple[tuple[OfficialAccountMediaResult, bytes], ...],
) -> tuple[tuple[EditorHandoffMediaAsset, ...], dict[str, bytes]]:
    body_rows = sorted(
        (item for item in media if item[0].role == "body"),
        key=lambda item: item[0].ordinal,
    )
    context_rows = sorted(
        (item for item in media if item[0].role == "context"), key=lambda item: item[0].ordinal
    )
    cover_rows = [item for item in media if item[0].role == "cover"]
    if not 1 <= len(body_rows) <= 5 or len(cover_rows) != 1:
        raise ValueError("editor handoff requires body images and one cover")
    if tuple(item[0].ordinal for item in body_rows) != tuple(range(len(body_rows))):
        raise ValueError("editor handoff body ordinals must be contiguous")
    expected_body = tuple(
        (
            int(block.slot_key.removeprefix("body-")),
            section_index,
            block.alt_text,
        )
        for section_index, section in enumerate(article.sections)
        for block in section.blocks
        if isinstance(block, ArticleImageBlock)
    )
    if tuple(item[0].ordinal for item in body_rows) != tuple(
        ordinal for ordinal, _section_index, _alt_text in expected_body
    ):
        raise ValueError("editor handoff body media do not match article blocks")
    body_shape = {
        ordinal: (section_index, alt_text) for ordinal, section_index, alt_text in expected_body
    }
    expected_context = article.news_context_media.items if article.news_context_media else ()
    if len(expected_context) != len(context_rows):
        raise ValueError("editor handoff context media do not match article snapshot")
    context_shape = {item.ordinal: item for item in expected_context}

    assets: list[EditorHandoffMediaAsset] = []
    bodies: dict[str, bytes] = {}
    for result, body in [*body_rows, *context_rows]:
        width, height, detected = _image_metadata(body)
        if detected != result.media_type:
            raise ValueError("editor handoff media MIME does not match encoded bytes")
        media_type = cast(Literal["image/jpeg", "image/png", "image/webp"], detected)
        if result.role == "body":
            section_index, article_alt = body_shape[result.ordinal]
            if result.assigned_section_index not in {None, section_index}:
                raise ValueError("editor handoff body section anchor changed")
            if result.alt_text not in {None, "", article_alt}:
                raise ValueError("editor handoff body alt text changed")
            assigned_section_index = section_index
            alt = article_alt
            source_page_url = None
            caption = result.caption
            credit = None
            rights_status = None
            context_only_not_evidence = False
        else:
            snapshot = context_shape[result.ordinal]
            if (
                result.assigned_section_index != snapshot.section_index
                or result.sha256 != snapshot.sha256
                or detected != snapshot.media_type
                or width != snapshot.width
                or height != snapshot.height
                or result.alt_text != snapshot.alt_text
                or result.source_page_url != snapshot.source_page_url
                or result.caption != snapshot.caption
                or result.credit != snapshot.credit
                or result.rights_status != snapshot.rights_status
                or not result.context_only_not_evidence
            ):
                raise ValueError("editor handoff context media lineage changed")
            assigned_section_index = snapshot.section_index
            alt = snapshot.alt_text
            source_page_url = snapshot.source_page_url
            caption = snapshot.caption
            credit = snapshot.credit
            rights_status = cast(Literal["publish_permission_unverified"], snapshot.rights_status)
            context_only_not_evidence = True
        path = media_asset_path(result.role, result.ordinal, result.media_type)
        asset = EditorHandoffMediaAsset(
            path=path,
            role=result.role,
            ordinal=result.ordinal,
            media_type=media_type,
            byte_size=len(body),
            sha256=sha256(body).hexdigest(),
            width=width,
            height=height,
            alt_text=alt,
            assigned_section_index=assigned_section_index,
            source_page_url=source_page_url,
            caption=caption,
            credit=credit,
            rights_status=rights_status,
            context_only_not_evidence=context_only_not_evidence,
        )
        assets.append(asset)
        bodies[path] = body

    cover_result, cover_source = cover_rows[0]
    if cover_result.ordinal != 0:
        raise ValueError("editor handoff cover ordinal must be zero")
    _cover_width, _cover_height, detected_cover_media_type = _image_metadata(cover_source)
    if detected_cover_media_type != cover_result.media_type:
        raise ValueError("editor handoff cover MIME does not match encoded bytes")
    cover_body, cover_media_type, width, height = _wide_cover(cover_source)
    cover_path = media_asset_path("cover", 0, cover_media_type)
    typed_cover_media_type = cast(
        Literal["image/jpeg", "image/png", "image/webp"], cover_media_type
    )
    assets.append(
        EditorHandoffMediaAsset(
            path=cover_path,
            role="cover",
            ordinal=0,
            media_type=typed_cover_media_type,
            byte_size=len(cover_body),
            sha256=sha256(cover_body).hexdigest(),
            width=width,
            height=height,
            alt_text=f"{article.title}封面",
        )
    )
    bodies[cover_path] = cover_body
    if cover_result.role != "cover":  # pragma: no cover - partitioned above
        raise ValueError("editor handoff cover role is invalid")
    return tuple(assets), bodies


def _wide_cover(body: bytes) -> tuple[bytes, str, int, int]:
    width, height, media_type = _image_metadata(body)
    if abs(width / height - 2.35) <= 0.08:
        return body, media_type, width, height
    with Image.open(io.BytesIO(body)) as image:
        image.load()
        if width / height < 2.35:
            target_width = width
            target_height = max(1, round(target_width / 2.35))
            top = max(0, min((height - target_height) // 3, height - target_height))
            crop = image.crop((0, top, target_width, top + target_height))
        else:
            target_height = height
            target_width = max(1, round(target_height * 2.35))
            left = max(0, (width - target_width) // 2)
            crop = image.crop((left, 0, left + target_width, target_height))
        output = io.BytesIO()
        crop.save(output, format="PNG", optimize=False, compress_level=9)
    encoded = output.getvalue()
    final_width, final_height, _detected = _image_metadata(encoded)
    return encoded, "image/png", final_width, final_height


def _image_metadata(body: bytes) -> tuple[int, int, str]:
    with Image.open(io.BytesIO(body)) as image:
        image.load()
        media_type = {"JPEG": "image/jpeg", "PNG": "image/png", "WEBP": "image/webp"}.get(
            image.format or ""
        )
        if media_type is None:
            raise ValueError("editor handoff image encoding is unsupported")
        width, height = image.size
    if width < 1 or height < 1 or width > 8192 or height > 8192 or width * height > 32_000_000:
        raise ValueError("editor handoff image dimensions are unsafe")
    return width, height, media_type


def _preview_document(body_html: str) -> str:
    return (
        '<!doctype html><html lang="zh-CN"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        "<title>微信公众号编辑器本地交接</title></head>"
        '<body style="margin:0;background:#EEF5FB;color:#26364A;">'
        '<aside style="padding:12px;display:flex;gap:12px;align-items:center;'
        "justify-content:center;"
        'background:#0D57C8;color:#FFFFFF;font-family:sans-serif;">'
        '<button id="copy-button" type="button">复制到公众号编辑器</button>'
        '<span id="copy-status" role="status" aria-live="polite">本地交接，未同步公众号</span>'
        '</aside><main id="copy-root">'
        f"{body_html}</main><script>{PREVIEW_SCRIPT}</script></body></html>"
    )


def _safe_article_projection(article: ArticlePackage) -> dict[str, object]:
    return {
        "title": article.title,
        "digest": article.digest,
        "author": article.author,
        "lead": article.lead,
        "sections": [section.model_dump(mode="json") for section in article.sections],
        "conclusion": article.conclusion,
        "claims": [claim.model_dump(mode="json") for claim in article.claims],
        "sources": [source.model_dump(mode="json") for source in article.sources],
        "quality": article.quality.model_dump(mode="json"),
        "versions": article.versions.model_dump(mode="json"),
        "content_fingerprint": article.content_fingerprint,
    }


def _sources_projection(article: ArticlePackage) -> dict[str, object]:
    return {
        "boundary": "external facts require collected authoritative source text",
        "items": [source.model_dump(mode="json") for source in article.sources],
    }


def _rights_projection(media: tuple[EditorHandoffMediaAsset, ...]) -> dict[str, object]:
    return {
        "policy": "editor-handoff-context-rights-v1-direct-use-disclosed",
        "items": [item.model_dump(mode="json") for item in media if item.role == "context"],
        "disclosure": "新闻上下文图片按当前本地策略直接使用；发布权未验证。",
    }


def _review_projection(review: StoredOfficialAccountManualReview) -> dict[str, object]:
    return {
        "review_id": str(review.id),
        "decision": review.decision,
        "reviewer_label": review.reviewer_label,
        "note": review.note,
        "request_fingerprint": review.request_fingerprint,
        "reviewed_at": review.reviewed_at.isoformat(),
        "immutable": True,
    }


def _article_markdown(article: ArticlePackage, media: tuple[EditorHandoffMediaAsset, ...]) -> str:
    by_body = {item.ordinal: item for item in media if item.role == "body"}
    lines = [f"# {article.title}", "", f"> {article.lead}", ""]
    for section in article.sections:
        lines.extend((f"## {section.heading}", ""))
        for block in section.blocks:
            if isinstance(block, ArticleImageBlock):
                ordinal = int(block.slot_key.removeprefix("body-"))
                lines.extend((f"![{block.alt_text}]({by_body[ordinal].path})", ""))
            elif hasattr(block, "items"):
                lines.extend(f"- {item}" for item in block.items)
                lines.append("")
            else:
                lines.extend((block.text, ""))
    lines.extend(("## 写在最后", "", article.conclusion, ""))
    return "\n".join(lines)


def _readme(run_id: UUID, fingerprint: str, preflight: EditorHandoffPreflight) -> str:
    return (
        "# 微信公众号编辑器本地交接\n\n"
        "本交接包已通过结构与完整性预检，但没有连接、上传或发布到微信公众号。"
        "正式进入微信后，正文图仍需在编辑器中上传，封面仍需单独设置。\n\n"
        f"- Run ID: `{run_id}`\n"
        f"- Handoff fingerprint: `{fingerprint}`\n"
        f"- Preflight passed: `{str(preflight.passed).lower()}`\n"
        "- Mobile browser validation: `not_run`\n"
        "- Simulation/local only: `true`\n"
        "- Published: `false`\n\n"
        "新闻上下文图片按用户选择的本地策略直接保留。若 rights.json 显示 "
        "`publish_permission_unverified`，表示发布权未验证，并不表示已经授权。\n"
    )


def _json_bytes(value: object) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True, separators=(",", ": "))
        + "\n"
    ).encode("utf-8")


def _file_projection(path: str, body: bytes) -> dict[str, object]:
    _safe_path(path)
    return {"path": path, "byte_size": len(body), "sha256": sha256(body).hexdigest()}


def _safe_path(value: str) -> PurePosixPath:
    path = PurePosixPath(value)
    if path.is_absolute() or not path.parts or ".." in path.parts or "." in path.parts:
        raise ValueError("editor handoff archive path is unsafe")
    if any(not part or "\x00" in part for part in path.parts):
        raise ValueError("editor handoff archive path is unsafe")
    return path


def _deterministic_zip(files: Mapping[str, bytes], *, archive_root: str) -> bytes:
    output = io.BytesIO()
    with ZipFile(output, "w", compression=ZIP_DEFLATED, compresslevel=9) as archive:
        for relative in sorted(files):
            _safe_path(relative)
            info = ZipInfo(f"{archive_root}/{relative}", date_time=(1980, 1, 1, 0, 0, 0))
            info.compress_type = ZIP_DEFLATED
            info.external_attr = 0o100644 << 16
            archive.writestr(info, files[relative])
    return output.getvalue()


def _verify_zip(zip_bytes: bytes, *, files: Mapping[str, bytes], archive_root: str) -> None:
    expected = {f"{archive_root}/{path}": body for path, body in files.items()}
    with ZipFile(io.BytesIO(zip_bytes)) as archive:
        if archive.namelist() != sorted(expected):
            raise ValueError("editor handoff ZIP members are unstable")
        for path, body in expected.items():
            if archive.read(path) != body:
                raise ValueError("editor handoff ZIP member integrity failed")
