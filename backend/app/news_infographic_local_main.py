"""Operator-only local news-infographic preview CLI."""

# ruff: noqa: RUF001 -- approved Chinese Markdown labels are byte-exact.

from __future__ import annotations

import argparse
import asyncio
import json
import os
import stat
from hashlib import sha256
from pathlib import Path
from typing import cast
from uuid import UUID

import httpx

from app.application.ports.image_generation import ImageReference
from app.application.services.news_infographic import (
    _REVIEWED_CARDS_COPY_VERSION_V2,
    _REVIEWED_CARDS_PROMPT_VERSION_V2,
    _REVIEWED_CARDS_TRIAL_VERSION_V2,
    _RICH_WORLD_SKILLS_COPY_MD_SHA256,
    _RICH_WORLD_SKILLS_STYLE_SHA256,
    COPY_VERSION,
    GEOMETRY,
    PROMPT_VERSION,
    QUALITY_VERSION,
    ManualImageRetry,
    PosterCopy,
    ReviewedPosterCards,
    _hash,
    build_copy_audit_prompt,
    build_reviewed_card_copy,
    build_reviewed_rich_worldskills_copy,
    run_local_batch,
    validate_poster_copy,
    write_repaired_footer_run,
)
from app.application.services.news_infographic_footer import render_exact_source_footer
from app.core.config import get_settings
from app.domain.news_infographic import ValidatedInfographicInput
from app.infrastructure.ai.news_infographic import local_infographic_models
from app.infrastructure.news_infographic_local import (
    LocalInfographicPackageLoader,
    read_frozen_input_bundle,
    write_frozen_input_bundle,
)

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
_WORKSPACE_ROOT = (
    _PROJECT_ROOT.parents[2]
    if _PROJECT_ROOT.parent.name == "worktrees" and _PROJECT_ROOT.parent.parent.name == ".trellis"
    else _PROJECT_ROOT
)
_CHARACTER_REFERENCE = (
    _PROJECT_ROOT / "private/brand-materials/05-visual-assets/赛先生小赛-携手奔跑.png"
)
_APPROVED_SAMPLE = (
    _PROJECT_ROOT / "output/daily-news-infographic-preview-20260922/xiaosai-news-grain-v1.png"
)
_APPROVED_STYLE_SHA256 = "f37155958362b29a37fbeccb982c0c41ce1effb139bd6c9c70625cc2ac7aa453"
_ACCEPTED_HISTORICAL_PROMPT_VERSIONS = frozenset(
    {
        "daily-news-infographic-prompt-v1",
        "daily-news-infographic-prompt-v2",
        "daily-news-infographic-prompt-v3",
        PROMPT_VERSION,
    }
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Create a local-only Xiaosai news infographic preview"
    )
    modes = parser.add_subparsers(dest="mode", required=True)
    prepare = modes.add_parser(
        "prepare", help="freeze accepted package inputs using loopback GET only"
    )
    prepare.add_argument("--package-id", action="append", required=True, type=UUID)
    prepare.add_argument("--api-base-url", default="http://127.0.0.1:8000")
    prepare.add_argument("--output-dir", type=Path, required=True)
    preflight = modes.add_parser("preflight", help="validate an input bundle without model calls")
    preflight.add_argument("--input-bundle", type=Path, required=True)
    preflight.add_argument("--output-dir", type=Path, required=True)
    run = modes.add_parser("run", help="run bounded automatic generation from a frozen input")
    run.add_argument("--input-bundle", type=Path, required=True)
    run.add_argument("--output-dir", type=Path, required=True)
    run.add_argument("--execute", action="store_true", required=True)
    run.add_argument(
        "--exact-text-quality-trial",
        action="store_true",
        help="opt in to formal-prompt exact-text local quality assets; never sends",
    )
    run.add_argument(
        "--evidence-first-copy-trial",
        action="store_true",
        help="local exact-text trial using only frozen claims for copy; independent audit remains",
    )
    run.add_argument(
        "--model-rendered-text-trial",
        action="store_true",
        help="local comparison: model draws frozen body text and illustration; never sends",
    )
    run.add_argument(
        "--reference-style-trial",
        action="store_true",
        help="local one-case comparison with pinned Xiaosai character and layout references",
    )
    run.add_argument(
        "--rich-worldskills-trial",
        action="store_true",
        help="one frozen WorldSkills rich-copy/style local image attempt; never sends",
    )
    run.add_argument(
        "--reviewed-cards-json",
        type=Path,
        help="local-only, frozen-case-pinned editorial copy for the three middle cards",
    )
    run.add_argument(
        "--approved-asset-root",
        type=Path,
        help="local project root holding the two approved reference files (trial mode only)",
    )
    run.add_argument(
        "--reuse-accepted-copy-run",
        type=Path,
        help="reuse one matching, previously accepted local copy without new chat calls",
    )
    retry = modes.add_parser(
        "retry-image", help="one explicit local image attempt after a verified unknown V2 result"
    )
    retry.add_argument("--input-bundle", type=Path, required=True)
    retry.add_argument("--prior-run", type=Path, required=True)
    retry.add_argument("--reviewed-cards-json", type=Path, required=True)
    retry.add_argument("--approved-asset-root", type=Path, required=True)
    retry.add_argument("--output-dir", type=Path, required=True)
    retry.add_argument("--execute", action="store_true", required=True)
    report = modes.add_parser("report", help="read an existing run without model calls")
    report.add_argument("--run-dir", type=Path, required=True)
    repair = modes.add_parser(
        "repair-footer", help="fix a prior poster's source footer offline into a fresh directory"
    )
    repair.add_argument("--input-bundle", type=Path, required=True)
    repair.add_argument("--prior-run", type=Path, required=True)
    repair.add_argument("--output-dir", type=Path, required=True)
    return parser


def _print_safe(value: object) -> None:
    print(json.dumps(value, ensure_ascii=False, sort_keys=True))


def _fresh_dir(path: Path) -> None:
    if ".." in path.parts or any(parent.is_symlink() for parent in (path, *path.parents)):
        raise ValueError("output path must not contain traversal or symlinks")
    path.mkdir(mode=0o700, parents=False, exist_ok=False)


def _save_json(path: Path, value: object) -> None:
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", closefd=False) as handle:
            json.dump(value, handle, ensure_ascii=False, sort_keys=True)
            handle.flush()
            os.fsync(handle.fileno())
    finally:
        os.close(descriptor)


def _approved_references(
    *,
    asset_root: Path = _PROJECT_ROOT,
    exact_text_quality_trial: bool = False,
    reference_style_trial: bool = False,
    rich_worldskills_trial: bool = False,
) -> tuple[ImageReference, ...]:
    if rich_worldskills_trial and (reference_style_trial or not exact_text_quality_trial):
        raise ValueError("rich WorldSkills references require an isolated exact-text trial")
    if reference_style_trial and not exact_text_quality_trial:
        raise ValueError("reference-style trial requires exact-text quality trial")
    if exact_text_quality_trial:
        from app.application.services.wecom_news_infographic import _approved_reference

        character_reference = _approved_reference(asset_root=asset_root)
        if not reference_style_trial and not rich_worldskills_trial:
            return character_reference
    if asset_root.is_symlink() or not asset_root.is_dir():
        raise ValueError("approved local asset root is missing or unsafe")
    references: list[ImageReference] = []
    for role, path in (
        (
            "approved-characters",
            asset_root / _CHARACTER_REFERENCE.relative_to(_PROJECT_ROOT),
        ),
        (
            "approved-style",
            asset_root
            / (
                Path("output/daily-news-infographic-rich-preview-20260925-d.png")
                if rich_worldskills_trial
                else _APPROVED_SAMPLE.relative_to(_PROJECT_ROOT)
            ),
        ),
    ):
        if path.is_symlink() or not path.is_file():
            raise ValueError("approved local image reference is missing or unsafe")
        data = path.read_bytes()
        if len(data) > 4 * 1024 * 1024 or not data.startswith(b"\x89PNG\r\n\x1a\n"):
            raise ValueError("approved local reference is not a bounded PNG")
        references.append(
            ImageReference(
                role=role,
                asset_id=role,
                filename=path.name,
                sha256=sha256(data).hexdigest(),
                image_bytes=data,
                selection_reason="user-approved local character or layout comparator",
            )
        )
    if reference_style_trial:
        if (
            references[0].sha256 != character_reference[0].sha256
            or references[1].sha256 != _APPROVED_STYLE_SHA256
        ):
            raise ValueError("approved reference-style assets have changed")
        return (*character_reference, references[1])
    if rich_worldskills_trial:
        if (
            references[0].sha256 != character_reference[0].sha256
            or references[1].sha256 != _RICH_WORLD_SKILLS_STYLE_SHA256
        ):
            raise ValueError("approved rich reference assets have changed")
        return (*character_reference, references[1])
    return tuple(references)


def _read_reviewed_cards(path: Path) -> ReviewedPosterCards:
    if ".." in path.parts or any(parent.is_symlink() for parent in (path, *path.parents)):
        raise ValueError("reviewed cards path is unsafe")
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    try:
        info = os.fstat(descriptor)
        if not stat.S_ISREG(info.st_mode) or not 0 < info.st_size <= 4096:
            raise ValueError("reviewed cards are not a bounded regular file")
        with os.fdopen(descriptor, "rb", closefd=False) as handle:
            body = handle.read(4097)
    finally:
        os.close(descriptor)
    if len(body) > 4096:
        raise ValueError("reviewed cards exceed size limit")

    def unique_keys(pairs: list[tuple[str, object]]) -> dict[str, object]:
        value: dict[str, object] = {}
        for key, item in pairs:
            if key in value:
                raise ValueError("reviewed cards contain duplicate JSON keys")
            value[key] = item
        return value

    return ReviewedPosterCards.model_validate(json.loads(body, object_pairs_hook=unique_keys))


def _accepted_copy_from_run(path: Path, case: ValidatedInfographicInput) -> PosterCopy:
    output_root = (_PROJECT_ROOT / "output").resolve()
    if ".." in path.parts or any(parent.is_symlink() for parent in (path, *path.parents)):
        raise ValueError("accepted copy run path is unsafe")
    if not path.resolve(strict=True).is_relative_to(output_root):
        raise ValueError("accepted copy run must be under local output")
    documents: list[object] = []
    for name in ("manifest.json", "copy.json", "private/01-image-request.json"):
        target = path / name
        if target.parent.is_symlink() or target.is_symlink():
            raise ValueError("accepted copy run is missing a bounded artifact")
        try:
            descriptor = os.open(target, os.O_RDONLY | os.O_NOFOLLOW)
            try:
                info = os.fstat(descriptor)
                if not stat.S_ISREG(info.st_mode) or info.st_size > 128 * 1024:
                    raise ValueError("accepted copy run is missing a bounded artifact")
                with os.fdopen(descriptor, "rb", closefd=False) as handle:
                    body = handle.read(128 * 1024 + 1)
                if len(body) > 128 * 1024:
                    raise ValueError("accepted copy run is missing a bounded artifact")
            finally:
                os.close(descriptor)
        except OSError as exc:
            raise ValueError("accepted copy run is missing a bounded artifact") from exc
        documents.append(json.loads(body))
    try:
        manifest, copies, frozen_request = documents
        if (
            not isinstance(manifest, dict)
            or not isinstance(copies, list)
            or not isinstance(frozen_request, dict)
        ):
            raise ValueError("accepted copy artifacts have wrong shape")
        prior = manifest["cases"][0]
        record = copies[0]
        if (
            manifest["schema_version"] != QUALITY_VERSION
            or manifest["case_count"] != 1
            or len(manifest["cases"]) != 1
            or len(copies) != 1
            or prior["copy"] != "accepted"
            or prior.get("copy_provenance") == "frozen_claims_evidence_first_local"
            or prior["input_fingerprint"] != case.fingerprint
            or prior["package_id"] != str(case.package_id)
            or record["package_id"] != str(case.package_id)
            or record["source_footer"] != case.source_footer
            or frozen_request["schema_version"] not in _ACCEPTED_HISTORICAL_PROMPT_VERSIONS
            or frozen_request["input_fingerprint"] != case.fingerprint
            or frozen_request["package_id"] != str(case.package_id)
            or frozen_request["source_footer"] != case.source_footer
            or frozen_request["copy"] != record["copy"]
        ):
            raise ValueError("accepted copy does not match the frozen case")
        copy = PosterCopy.model_validate(record["copy"])
        validate_poster_copy(case, copy)
    except (KeyError, IndexError, TypeError) as exc:
        raise ValueError("accepted copy artifacts are incomplete") from exc
    return copy


def _bounded_regular_bytes(path: Path, *, maximum: int) -> bytes:
    if path.is_symlink() or path.parent.is_symlink():
        raise ValueError("offline repair artifact path is unsafe")
    try:
        descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
        try:
            info = os.fstat(descriptor)
            if not stat.S_ISREG(info.st_mode) or info.st_size > maximum:
                raise ValueError("offline repair artifact is not a bounded regular file")
            with os.fdopen(descriptor, "rb", closefd=False) as handle:
                body = handle.read(maximum + 1)
            if len(body) > maximum:
                raise ValueError("offline repair artifact exceeds size limit")
            return body
        finally:
            os.close(descriptor)
    except OSError as exc:
        raise ValueError("offline repair artifact cannot be read") from exc


def _verify_rich_worldskills_document(
    body: bytes, case: ValidatedInfographicInput, copy: PosterCopy
) -> None:
    """Ensure the pinned reviewed Markdown really contains the frozen rendered copy."""
    try:
        lines = [line.strip() for line in body.decode("utf-8").splitlines()]
    except UnicodeDecodeError as exc:
        raise ValueError("approved rich copy document is not UTF-8") from exc

    def unique_value(prefix: str) -> str:
        matches = [line.removeprefix(prefix) for line in lines if line.startswith(prefix)]
        if len(matches) != 1 or not matches[0]:
            raise ValueError("approved rich copy document structure differs")
        return matches[0]

    if (
        unique_value("主标题：") != copy.title
        or unique_value("导语：") != copy.news_summary
        or unique_value("原文链接：") != case.source_url
        or unique_value("页脚：")
        != f"新闻日期：{case.source_date.isoformat()}　新闻来源：{case.source_name}"
    ):
        raise ValueError("approved rich copy document differs from frozen copy/source")
    for label, card in zip(("蓝色卡｜", "绿色卡｜", "紫色卡｜"), copy.cards, strict=True):
        positions = [index for index, line in enumerate(lines) if line.startswith(label)]
        if len(positions) != 1 or lines[positions[0]].removeprefix(label) != card.heading:
            raise ValueError("approved rich card heading differs")
        following = [line for line in lines[positions[0] + 1 :] if line]
        if not following or following[0] != card.body:
            raise ValueError("approved rich card body differs")


def _verified_manual_image_retry(
    path: Path,
    output_dir: Path,
    output_root: Path,
    case: ValidatedInfographicInput,
    reviewed: ReviewedPosterCards,
    references: tuple[ImageReference, ...],
    copy_model: str,
) -> tuple[PosterCopy, ManualImageRetry]:
    """Read an immutable accepted V2 unknown without re-running its stochastic audit."""
    if (
        ".." in path.parts
        or ".." in output_dir.parts
        or any(
            parent.is_symlink() for parent in (path, *path.parents, output_dir, *output_dir.parents)
        )
        or output_root.is_symlink()
        or not output_root.is_dir()
        or not path.resolve(strict=True).is_dir()
        or path.resolve(strict=True).parent != output_dir.parent.resolve(strict=True)
        or path.resolve(strict=True).parent != output_root.resolve(strict=True)
        or output_dir.exists()
        or output_dir == path
    ):
        raise ValueError("manual retry requires a fresh sibling of the prior run")

    def read_json(name: str) -> object:
        body = _bounded_regular_bytes(path / name, maximum=128 * 1024)

        def unique_keys(pairs: list[tuple[str, object]]) -> dict[str, object]:
            value: dict[str, object] = {}
            for key, item in pairs:
                if key in value:
                    raise ValueError("manual retry parent has duplicate JSON keys")
                value[key] = item
            return value

        return json.loads(body, object_pairs_hook=unique_keys)

    manifest = read_json("manifest.json")
    quality = read_json("quality.json")
    copies = read_json("copy.json")
    request = read_json("private/01-image-request.json")
    image_intent = read_json("private/01-image.intent.json")
    audit_intent = read_json("private/01-copy-audit.intent.json")
    audit = read_json("private/01-copy-audit-verdict.json")
    candidate = read_json("private/01-copy-candidate.json")
    evidence = read_json("evidence.json")
    if not all(
        isinstance(item, dict)
        for item in (manifest, request, image_intent, audit_intent, audit, candidate)
    ) or not all(isinstance(item, list) for item in (quality, copies, evidence)):
        raise ValueError("manual retry parent artifacts have invalid shapes")
    manifest = cast(dict[str, object], manifest)
    request = cast(dict[str, object], request)
    image_intent = cast(dict[str, object], image_intent)
    audit_intent = cast(dict[str, object], audit_intent)
    audit = cast(dict[str, object], audit)
    candidate = cast(dict[str, object], candidate)
    quality = cast(list[object], quality)
    copies = cast(list[object], copies)
    evidence = cast(list[object], evidence)
    if (
        manifest.get("schema_version") != QUALITY_VERSION
        or manifest.get("case_count") != 1
        or manifest.get("trial_version") != _REVIEWED_CARDS_TRIAL_VERSION_V2
        or manifest.get("prompt_version") != _REVIEWED_CARDS_PROMPT_VERSION_V2
        or manifest.get("copy_policy_version") != _REVIEWED_CARDS_COPY_VERSION_V2
        or manifest.get("send_ready") is not False
        or manifest.get("cases") != quality
        or len(quality) != 1
        or len(copies) != 1
        or len(evidence) != 1
        or not isinstance(quality[0], dict)
        or not isinstance(copies[0], dict)
    ):
        raise ValueError("manual retry parent has no accepted single-case V2 record")
    prior = cast(dict[str, object], quality[0])
    record = cast(dict[str, object], copies[0])
    if not isinstance(evidence[0], dict):
        raise ValueError("manual retry parent evidence has invalid shape")
    evidence_record = cast(dict[str, object], evidence[0])
    expected_copy = build_reviewed_card_copy(case, reviewed)
    copy_data = expected_copy.model_dump(mode="json")
    expected_audit_fingerprint = _hash(
        (
            _REVIEWED_CARDS_COPY_VERSION_V2,
            case.fingerprint,
            copy_data,
            build_copy_audit_prompt(case, expected_copy),
            copy_model,
        )
    )
    if (
        any(prior.get(key) != value for key, value in case.public_projection().items())
        or prior.get("copy") != "accepted"
        or prior.get("copy_policy_version") != _REVIEWED_CARDS_COPY_VERSION_V2
        or prior.get("copy_provenance") != "reviewed_claim_bound_cards_local"
        or prior.get("generation") != "result_unknown"
        or prior.get("reason_code") != "image_provider_unavailable"
        or prior.get("decode") != "not_checked"
        or prior.get("footer") != "not_checked"
        or any(key in prior for key in ("image", "image_sha256", "derived_image", "group_image"))
        or record.get("package_id") != str(case.package_id)
        or record.get("source_footer") != case.source_footer
        or record.get("copy") != copy_data
        or record.get("copy_policy_version") != _REVIEWED_CARDS_COPY_VERSION_V2
        or record.get("copy_provenance") != "reviewed_claim_bound_cards_local"
        or evidence_record.get("input_fingerprint") != case.fingerprint
        or candidate.get("schema_version") != COPY_VERSION
        or candidate.get("copy") != copy_data
        or candidate.get("copy_policy_version") != _REVIEWED_CARDS_COPY_VERSION_V2
        or candidate.get("package_id") != str(case.package_id)
        or audit.get("schema_version") != COPY_VERSION
        or audit.get("copy_policy_version") != _REVIEWED_CARDS_COPY_VERSION_V2
        or audit.get("package_id") != str(case.package_id)
        or audit.get("accepted") is not True
        or audit.get("issues") != []
        or audit.get("issue_codes") != []
        or audit_intent.get("stage") != "copy-audit"
        or audit_intent.get("case_ordinal") != 1
        or audit_intent.get("state") != "reserved"
        or audit_intent.get("request_fingerprint") != expected_audit_fingerprint
    ):
        raise ValueError("manual retry prior copy, audit or news identity differs")
    images_dir = path / "images"
    if images_dir.is_symlink() or not images_dir.is_dir() or any(images_dir.iterdir()):
        raise ValueError("manual retry parent already has image bytes")
    private_dir = path / "private"
    if private_dir.is_symlink() or len(list(private_dir.glob("*image.intent.json"))) != 1:
        raise ValueError("manual retry parent has an ambiguous image intent count")
    expected_references = [{"role": ref.role, "sha256": ref.sha256} for ref in references]
    fingerprint = request.get("request_fingerprint")
    frozen_prompt = request.get("prompt")
    image_model = request.get("model")
    if (
        request.get("schema_version") != _REVIEWED_CARDS_PROMPT_VERSION_V2
        or request.get("trial_version") != _REVIEWED_CARDS_TRIAL_VERSION_V2
        or request.get("copy_provenance") != "reviewed_claim_bound_cards_local"
        or request.get("body_rendering") != "model"
        or request.get("input_fingerprint") != case.fingerprint
        or request.get("package_id") != str(case.package_id)
        or request.get("source_footer") != case.source_footer
        or request.get("copy") != copy_data
        or request.get("references") != expected_references
        or request.get("geometry") != {"width": GEOMETRY[0], "height": GEOMETRY[1]}
        or request.get("provider") != "comfly"
        or image_model != "gpt-image-2.5-sunburst"
        or not isinstance(frozen_prompt, str)
        or image_intent.get("stage") != "image"
        or image_intent.get("case_ordinal") != 1
        or image_intent.get("state") != "reserved"
        or image_intent.get("request_fingerprint") != fingerprint
    ):
        raise ValueError("manual retry prior image request differs")
    if (
        not isinstance(fingerprint, str)
        or len(fingerprint) != 64
        or not isinstance(frozen_prompt, str)
        or not isinstance(image_model, str)
    ):
        raise ValueError("manual retry parent fingerprint is invalid")
    return expected_copy, ManualImageRetry(
        parent_request_fingerprint=fingerprint,
        parent_run_name=path.name,
        frozen_prompt=frozen_prompt,
        model=image_model,
    )


def _manual_retry_output_root(asset_root: Path) -> Path:
    """Manual paid retries are confined to this checkout's real workspace output."""
    if any(
        parent.is_symlink() for parent in (asset_root, *asset_root.parents)
    ) or asset_root.resolve(strict=True) != _WORKSPACE_ROOT.resolve(strict=True):
        raise ValueError("manual retry asset root must be the project workspace")
    output_root = _WORKSPACE_ROOT / "output"
    if output_root.is_symlink() or not output_root.is_dir():
        raise ValueError("workspace output root must be a real directory")
    return output_root


def _verified_prior_footer_artifacts(
    path: Path, case: ValidatedInfographicInput
) -> tuple[dict[str, object], dict[str, object], bytes]:
    output_root = (_PROJECT_ROOT / "output").resolve()
    if ".." in path.parts or any(parent.is_symlink() for parent in (path, *path.parents)):
        raise ValueError("prior run path is unsafe")
    resolved = path.resolve(strict=True)
    if not resolved.is_relative_to(output_root) or not resolved.is_dir():
        raise ValueError("prior run must be an existing local output directory")

    def read_json(name: str) -> object:
        return json.loads(_bounded_regular_bytes(path / name, maximum=128 * 1024))

    manifest = read_json("manifest.json")
    quality = read_json("quality.json")
    copies = read_json("copy.json")
    request = read_json("private/01-image-request.json")
    if (
        not isinstance(manifest, dict)
        or not isinstance(quality, list)
        or not isinstance(copies, list)
        or not isinstance(request, dict)
        or manifest.get("schema_version") != QUALITY_VERSION
        or manifest.get("case_count") != 1
        or not isinstance(manifest.get("cases"), list)
        or len(manifest["cases"]) != 1
        or quality != manifest["cases"]
        or len(copies) != 1
    ):
        raise ValueError("prior run has inconsistent manifest or copy artifacts")
    prior = manifest["cases"][0]
    record = copies[0]
    if not isinstance(prior, dict) or not isinstance(record, dict):
        raise ValueError("prior run has malformed case artifacts")
    if (
        prior.get("generation") != "generated"
        or prior.get("decode") != "passed"
        or prior.get("package_id") != str(case.package_id)
        or prior.get("input_fingerprint") != case.fingerprint
        or prior.get("source_date") != case.source_date.isoformat()
        or prior.get("source_name") != case.source_name
        or prior.get("source_url") != case.source_url
        or prior.get("copy_provenance") == "frozen_claims_evidence_first_local"
        or record.get("package_id") != str(case.package_id)
        or record.get("source_footer") != case.source_footer
        or request.get("schema_version") not in _ACCEPTED_HISTORICAL_PROMPT_VERSIONS
        or request.get("input_fingerprint") != case.fingerprint
        or request.get("package_id") != str(case.package_id)
        or request.get("source_footer") != case.source_footer
        or request.get("copy") != record.get("copy")
    ):
        raise ValueError("prior run does not match the frozen source input")
    copy = PosterCopy.model_validate(record["copy"])
    validate_poster_copy(case, copy)
    media_type = prior.get("media_type")
    if not isinstance(media_type, str):
        raise ValueError("prior image media type is invalid")
    extension = {"image/png": "png", "image/jpeg": "jpg", "image/webp": "webp"}.get(media_type)
    expected_path = f"images/01-{case.package_id}.{extension}"
    if extension is None or prior.get("image") != expected_path:
        raise ValueError("prior image path or media type is invalid")
    body = _bounded_regular_bytes(path / expected_path, maximum=24 * 1024 * 1024)
    if sha256(body).hexdigest() != prior.get("image_sha256"):
        raise ValueError("prior image checksum differs from manifest")
    return prior, record, body


async def _run(args: argparse.Namespace) -> int:
    if args.mode == "report":
        path = args.run_dir / "manifest.json"
        if path.is_file():
            _print_safe(json.loads(path.read_text(encoding="utf-8")))
            return 0
        intents = sorted(item.name for item in (args.run_dir / "private").glob("*.intent.json"))
        _print_safe(
            {
                "status": "incomplete_or_interrupted",
                "reserved_intents": [
                    {"intent": item, "outcome": "result_unknown_requires_inspection"}
                    for item in intents
                ],
                "replay_allowed": False,
            }
        )
        return 2
    if args.mode == "prepare":
        package_ids = tuple(args.package_id)
        async with httpx.AsyncClient(trust_env=False, follow_redirects=False) as client:
            cases = await LocalInfographicPackageLoader(client).load(
                package_ids, api_base_url=args.api_base_url
            )
        _fresh_dir(args.output_dir)
        write_frozen_input_bundle(args.output_dir / "input.json", cases)
        _print_safe(
            {
                "status": "prepared",
                "input_bundle": str(args.output_dir / "input.json"),
                "cases": [item.public_projection() for item in cases],
            }
        )
        return 0
    if args.mode == "repair-footer":
        cases = read_frozen_input_bundle(args.input_bundle)
        if len(cases) != 1:
            raise ValueError("footer repair requires exactly one frozen case")
        if args.output_dir.parent.resolve(strict=True) != args.prior_run.parent.resolve(
            strict=True
        ):
            raise ValueError("offline repair output must be a fresh sibling of the prior run")
        if args.output_dir.resolve(strict=False).is_relative_to(
            args.prior_run.resolve(strict=True)
        ):
            raise ValueError("offline repair must not write inside the prior run")
        case = cases[0]
        prior, record, original_bytes = _verified_prior_footer_artifacts(args.prior_run, case)
        rendered = render_exact_source_footer(original_bytes, case)
        summary = write_repaired_footer_run(
            case=case,
            output_dir=args.output_dir,
            prior_run_name=args.prior_run.name,
            prior_outcome=prior,
            copy_record=record,
            original_bytes=original_bytes,
            rendered=rendered,
        )
        _print_safe(
            {
                "status": "repaired_local_unpublished",
                "run_dir": str(summary.run_dir),
                "model_calls": 0,
                "original_image_sha256": prior["image_sha256"],
                "derived_image_sha256": rendered.image_sha256,
                "batch_accepted": False,
            }
        )
        return 0
    cases = read_frozen_input_bundle(args.input_bundle)
    if args.mode == "preflight":
        _fresh_dir(args.output_dir)
        _save_json(
            args.output_dir / "preflight.json",
            {
                "status": "valid",
                "cases": [item.public_projection() for item in cases],
                "model_calls": 0,
            },
        )
        _print_safe({"status": "valid", "case_count": len(cases), "model_calls": 0})
        return 0
    if args.mode == "retry-image":
        if len(cases) != 1:
            raise ValueError("manual image retry requires exactly one frozen case")
        output_root = _manual_retry_output_root(args.approved_asset_root)
        retry_reviewed_cards = _read_reviewed_cards(args.reviewed_cards_json)
        references = _approved_references(
            asset_root=args.approved_asset_root,
            exact_text_quality_trial=True,
            reference_style_trial=True,
        )
        settings = get_settings()
        retry_accepted_copy, retry = _verified_manual_image_retry(
            args.prior_run,
            args.output_dir,
            output_root,
            cases[0],
            retry_reviewed_cards,
            references,
            settings.ai_chat_model,
        )
        async with local_infographic_models(settings) as models:
            summary = await run_local_batch(
                cases,
                run_dir=args.output_dir,
                models=models,
                references=references,
                accepted_copy=retry_accepted_copy,
                exact_text_quality_trial=True,
                evidence_first_copy_trial=True,
                model_rendered_text_trial=True,
                reference_style_trial=True,
                reviewed_cards=retry_reviewed_cards,
                manual_image_retry=retry,
            )
        _print_safe(
            {
                "status": "local_manual_image_retry_pending_review",
                "run_dir": str(summary.run_dir),
                "send_ready": False,
                "batch_accepted": summary.batch_accepted,
                "cases": list(summary.cases),
            }
        )
        return 0
    if args.mode == "run":
        if args.rich_worldskills_trial:
            if (
                args.exact_text_quality_trial
                or args.evidence_first_copy_trial
                or args.model_rendered_text_trial
                or args.reference_style_trial
                or args.reviewed_cards_json is not None
                or args.reuse_accepted_copy_run is not None
            ):
                raise ValueError("rich WorldSkills trial cannot mix with older trial modes")
            if len(cases) != 1:
                raise ValueError("rich WorldSkills trial requires one frozen case")
            asset_root = args.approved_asset_root or _WORKSPACE_ROOT
            output_root = _manual_retry_output_root(asset_root)
            if args.output_dir.parent.resolve(strict=True) != output_root.resolve(strict=True):
                raise ValueError("rich WorldSkills output must be a fresh workspace output child")
            approved_copy_doc = (
                asset_root
                / "output/daily-news-infographic-reference-match-skills-20260925-b.copy.md"
            )
            approved_copy_body = _bounded_regular_bytes(approved_copy_doc, maximum=8192)
            if sha256(approved_copy_body).hexdigest() != _RICH_WORLD_SKILLS_COPY_MD_SHA256:
                raise ValueError("approved rich copy document has changed")
            _verify_rich_worldskills_document(
                approved_copy_body, cases[0], build_reviewed_rich_worldskills_copy(cases[0])
            )
        if args.evidence_first_copy_trial and not args.exact_text_quality_trial:
            raise ValueError("evidence-first copy requires exact-text quality trial")
        if args.evidence_first_copy_trial and args.reuse_accepted_copy_run is not None:
            raise ValueError("evidence-first copy cannot reuse a prior run")
        if args.model_rendered_text_trial and not (
            args.exact_text_quality_trial and args.evidence_first_copy_trial
        ):
            raise ValueError("model-rendered text requires evidence-first exact-text trial")
        if args.model_rendered_text_trial and args.reuse_accepted_copy_run is not None:
            raise ValueError("model-rendered text cannot reuse a prior run")
        if args.reference_style_trial and not (
            args.exact_text_quality_trial
            and args.evidence_first_copy_trial
            and args.model_rendered_text_trial
        ):
            raise ValueError(
                "reference-style requires model-rendered evidence-first exact-text trial"
            )
        if args.reference_style_trial and len(cases) != 1:
            raise ValueError("reference-style trial requires exactly one case")
        if args.reviewed_cards_json is not None and not args.reference_style_trial:
            raise ValueError("reviewed cards require reference-style trial")
        if args.reviewed_cards_json is not None and args.reuse_accepted_copy_run is not None:
            raise ValueError("reviewed cards cannot reuse a prior run")
        reviewed_cards = (
            _read_reviewed_cards(args.reviewed_cards_json)
            if args.reviewed_cards_json is not None
            else None
        )
        if reviewed_cards is not None:
            build_reviewed_card_copy(cases[0], reviewed_cards)
        if args.approved_asset_root is not None and not (
            args.exact_text_quality_trial or args.rich_worldskills_trial
        ):
            raise ValueError("approved asset root override requires exact-text quality trial")
        references = _approved_references(
            asset_root=args.approved_asset_root
            or (_WORKSPACE_ROOT if args.rich_worldskills_trial else _PROJECT_ROOT),
            exact_text_quality_trial=args.exact_text_quality_trial or args.rich_worldskills_trial,
            reference_style_trial=args.reference_style_trial,
            rich_worldskills_trial=args.rich_worldskills_trial,
        )
        accepted_copy = None
        if args.reuse_accepted_copy_run is not None:
            if len(cases) != 1:
                raise ValueError("accepted copy reuse requires exactly one case")
            accepted_copy = _accepted_copy_from_run(args.reuse_accepted_copy_run, cases[0])
        settings = get_settings()
        async with local_infographic_models(settings) as models:
            summary = await run_local_batch(
                cases,
                run_dir=args.output_dir,
                models=models,
                references=references,
                accepted_copy=accepted_copy,
                exact_text_quality_trial=args.exact_text_quality_trial
                or args.rich_worldskills_trial,
                evidence_first_copy_trial=args.evidence_first_copy_trial
                or args.rich_worldskills_trial,
                model_rendered_text_trial=args.model_rendered_text_trial
                or args.rich_worldskills_trial,
                reference_style_trial=args.reference_style_trial,
                reviewed_cards=reviewed_cards,
                rich_worldskills_trial=args.rich_worldskills_trial,
            )
        trial_assets_complete = (
            args.exact_text_quality_trial or args.rich_worldskills_trial
        ) and all(case.get("group_image_sha256") for case in summary.cases)
        _print_safe(
            {
                "status": (
                    "local_quality_assets_pending_review"
                    if trial_assets_complete
                    else "local_quality_trial_incomplete"
                    if args.exact_text_quality_trial or args.rich_worldskills_trial
                    else "finished"
                ),
                "run_dir": str(summary.run_dir),
                "batch_accepted": summary.batch_accepted,
                **(
                    {"send_ready": False}
                    if args.exact_text_quality_trial or args.rich_worldskills_trial
                    else {}
                ),
                "cases": list(summary.cases),
            }
        )
        return 0 if trial_assets_complete or summary.batch_accepted else 2
    raise ValueError("unsupported local infographic mode")


def main() -> int:
    try:
        return asyncio.run(_run(_parser().parse_args()))
    except (ValueError, RuntimeError, OSError) as exc:
        _print_safe({"status": "error", "reason": type(exc).__name__})
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
