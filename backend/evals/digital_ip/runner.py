"""Run and verify the provider-free digital-IP fixture contract baseline."""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from datetime import date
from hashlib import sha256
from pathlib import Path

from app.domain.brand_knowledge import BrandAudience
from app.domain.digital_ip import (
    DigitalIpDocumentBinding,
    DigitalIpProfile,
    DigitalIpVisualAsset,
    DigitalIpVisualCatalogProjection,
    DigitalIpVisualCatalogStatus,
    project_digital_ip_profile,
)

from .dataset import DEFAULT_CASES_PATH, DigitalIpEvalDatasetError, load_eval_cases
from .metrics import DigitalIpEvalReport, build_report, score_case
from .models import CASE_SCHEMA_VERSION, DigitalIpEvalCase
from .reporting import canonical_json, render_markdown

FEATURE_ROOT = Path(__file__).resolve().parent
CANONICAL_JSON_PATH = FEATURE_ROOT / "canonical-report.json"
CANONICAL_MARKDOWN_PATH = FEATURE_ROOT / "canonical-report.md"


def evaluate_path(path: Path = DEFAULT_CASES_PATH) -> DigitalIpEvalReport:
    cases = load_eval_cases(path)
    try:
        dataset_bytes = path.read_bytes()
    except OSError as exc:
        raise DigitalIpEvalDatasetError(
            "digital IP eval dataset could not be read for hashing"
        ) from exc
    scores = tuple(score_case(case, _profile_for_case(case)) for case in cases)
    dataset_hash = sha256(dataset_bytes).hexdigest()[:16]
    return build_report(
        dataset_version=f"{CASE_SCHEMA_VERSION}:{dataset_hash}",
        scores=scores,
    )


def _profile_for_case(case: DigitalIpEvalCase) -> DigitalIpProfile:
    bindings = tuple(
        DigitalIpDocumentBinding(
            document_id=document.document_id,
            version_id=document.version_id,
            version=1,
            title=document.title,
            document_kind=document.document_kind,
            audience=BrandAudience.PARENTS,
            valid_from=date(2026, 1, 1),
            valid_until=None,
            tone_tags=document.tone_tags,
            safety_tags=document.safety_tags,
            visual_tags=document.visual_tags,
        )
        for document in case.documents
    )
    assets = tuple(
        DigitalIpVisualAsset(
            asset_ref=asset.asset_ref,
            checksum_ref=asset.asset_ref,
            display_name=asset.display_name,
            asset_kind=asset.asset_kind,
            characters=asset.characters,
            roles=asset.roles,
            topics=asset.topics,
            poses=asset.poses,
            scene_tags=asset.scene_tags,
            width=1024,
            height=1024,
            approved=True,
            priority=100,
        )
        for asset in case.visual_assets
    )
    visual = DigitalIpVisualCatalogProjection(
        status=(
            DigitalIpVisualCatalogStatus.READY if assets else DigitalIpVisualCatalogStatus.EMPTY
        ),
        catalog_version="fixture-visual-catalog-v1",
        assets=assets,
    )
    return project_digital_ip_profile(bindings, visual)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--check", action="store_true")
    mode.add_argument("--write-canonical", action="store_true")
    parser.add_argument("--cases", type=Path, default=DEFAULT_CASES_PATH)
    args = parser.parse_args(argv)
    try:
        report = evaluate_path(args.cases)
    except (DigitalIpEvalDatasetError, RuntimeError, ValueError) as exc:
        print(f"digital IP eval failed: {exc}", file=sys.stderr)
        return 1
    if report.aggregate.failed_case_ids or report.aggregate.brand_as_fact_count:
        print("digital IP eval contract failures detected", file=sys.stderr)
        return 1
    rendered_json = canonical_json(report)
    rendered_markdown = render_markdown(report)
    if args.write_canonical:
        CANONICAL_JSON_PATH.write_text(rendered_json, encoding="utf-8")
        CANONICAL_MARKDOWN_PATH.write_text(rendered_markdown, encoding="utf-8")
    elif args.check and not _artifacts_match(rendered_json, rendered_markdown):
        print("digital IP eval canonical report drifted", file=sys.stderr)
        return 1
    print(
        f"digital IP eval passed: {report.aggregate.passed_count}/"
        f"{report.aggregate.case_count}; fact violations=0"
    )
    return 0


def _artifacts_match(rendered_json: str, rendered_markdown: str) -> bool:
    try:
        return (
            CANONICAL_JSON_PATH.read_text(encoding="utf-8") == rendered_json
            and CANONICAL_MARKDOWN_PATH.read_text(encoding="utf-8") == rendered_markdown
        )
    except OSError:
        return False


if __name__ == "__main__":
    raise SystemExit(main())
