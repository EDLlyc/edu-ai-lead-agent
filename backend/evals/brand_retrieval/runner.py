"""Run the provider-free brand-text retrieval policy evaluation."""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from hashlib import sha256
from pathlib import Path
from uuid import NAMESPACE_URL, UUID, uuid5

from app.domain.brand_knowledge import (
    LEGACY_BRAND_RETRIEVAL_VERSION,
    STRUCTURED_BRAND_RETRIEVAL_VERSION,
    BrandAudience,
    BrandDocumentKind,
    BrandRetrievalHit,
    fuse_brand_retrieval_score,
)
from app.domain.brand_retrieval import RankedBrandHit, select_diverse_brand_hits

from .dataset import (
    DEFAULT_CASES_PATH,
    BrandRetrievalEvalDatasetError,
    load_eval_cases,
)
from .metrics import BrandRetrievalCaseScore, BrandRetrievalEvalReport, build_report, score_case
from .models import CASE_SCHEMA_VERSION, BrandRetrievalEvalCandidate, BrandRetrievalEvalCase
from .reporting import canonical_json, render_markdown

FEATURE_ROOT = Path(__file__).resolve().parent
CANONICAL_JSON_PATH = FEATURE_ROOT / "canonical-report.json"
CANONICAL_MARKDOWN_PATH = FEATURE_ROOT / "canonical-report.md"


def evaluate_path(path: Path = DEFAULT_CASES_PATH) -> BrandRetrievalEvalReport:
    cases = load_eval_cases(path)
    try:
        dataset_bytes = path.read_bytes()
    except OSError as exc:
        raise BrandRetrievalEvalDatasetError(
            "brand retrieval eval dataset could not be read for hashing"
        ) from exc
    scores = tuple(_score_observation(case) for case in cases)
    dataset_hash = sha256(dataset_bytes).hexdigest()[:16]
    return build_report(
        dataset_version=f"{CASE_SCHEMA_VERSION}:{dataset_hash}",
        scores=scores,
    )


def _score_observation(case: BrandRetrievalEvalCase) -> BrandRetrievalCaseScore:
    ranked = tuple(_ranked_hit(case, candidate) for candidate in case.candidates)
    legacy = select_diverse_brand_hits(
        ranked,
        limit=5,
        retrieval_version=LEGACY_BRAND_RETRIEVAL_VERSION,
    )
    structured = select_diverse_brand_hits(
        ranked,
        limit=5,
        retrieval_version=STRUCTURED_BRAND_RETRIEVAL_VERSION,
    )
    candidate_id_by_chunk = {
        _uuid(case.case_id, candidate.candidate_id): candidate.candidate_id
        for candidate in case.candidates
    }
    return score_case(
        case=case,
        legacy_ids=tuple(candidate_id_by_chunk[hit.chunk_id] for hit in legacy),
        structured_ids=tuple(candidate_id_by_chunk[hit.chunk_id] for hit in structured),
    )


def _ranked_hit(
    case: BrandRetrievalEvalCase,
    candidate: BrandRetrievalEvalCandidate,
) -> RankedBrandHit:
    full_text_score = 0.0 if candidate.full_text_rank is None else 1.0 / candidate.full_text_rank
    vector_score = 0.0 if candidate.vector_rank is None else 1.0 / candidate.vector_rank
    return RankedBrandHit(
        hit=BrandRetrievalHit(
            chunk_id=_uuid(case.case_id, candidate.candidate_id),
            document_id=_uuid(case.case_id, candidate.document_key),
            version_id=_uuid(case.case_id, candidate.version_key),
            document_title=f"fixture-{candidate.document_key}",
            document_kind=BrandDocumentKind.OTHER,
            audience=BrandAudience.PARENTS,
            text=f"sanitized fixture {candidate.candidate_id}",
            tone_tags=(),
            safety_tags=(),
            visual_tags=(),
            full_text_score=full_text_score,
            vector_score=vector_score,
            fused_score=fuse_brand_retrieval_score(
                full_text_rank=candidate.full_text_rank,
                vector_rank=candidate.vector_rank,
            ),
            section_id=_uuid(case.case_id, candidate.section_key),
            content_type=candidate.content_type,
            claim_scope=candidate.claim_scope,
            verification_required=candidate.verification_required,
        ),
        ordinal=candidate.ordinal,
    )


def _uuid(case_id: str, identifier: str) -> UUID:
    return uuid5(NAMESPACE_URL, f"brand-retrieval-eval:{case_id}:{identifier}")


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--check", action="store_true")
    mode.add_argument("--write-canonical", action="store_true")
    parser.add_argument("--cases", type=Path, default=DEFAULT_CASES_PATH)
    args = parser.parse_args(argv)
    try:
        report = evaluate_path(args.cases)
    except (BrandRetrievalEvalDatasetError, RuntimeError, ValueError) as exc:
        print(f"brand retrieval eval failed: {exc}", file=sys.stderr)
        return 1
    aggregate = report.aggregate
    failed = bool(
        aggregate.failed_case_ids
        or aggregate.passed_count != aggregate.case_count
        or aggregate.structured_v3.macro_recall_at_5 < aggregate.legacy_v2.macro_recall_at_5
        or aggregate.structured_v3.macro_mrr_at_5 < aggregate.legacy_v2.macro_mrr_at_5
        or aggregate.structured_v3.macro_ndcg_at_5 < aggregate.legacy_v2.macro_ndcg_at_5
        or aggregate.parent_diversity_delta <= 0
        or aggregate.legacy_v2.verification_coverage != 1.0
        or aggregate.structured_v3.verification_coverage != 1.0
        or aggregate.legacy_v2.brand_as_fact_violation_count
        or aggregate.structured_v3.brand_as_fact_violation_count
    )
    if failed:
        print("brand retrieval eval gates failed", file=sys.stderr)
        return 1
    rendered_json = canonical_json(report)
    rendered_markdown = render_markdown(report)
    if args.write_canonical:
        CANONICAL_JSON_PATH.write_text(rendered_json, encoding="utf-8")
        CANONICAL_MARKDOWN_PATH.write_text(rendered_markdown, encoding="utf-8")
    elif args.check and not _artifacts_match(rendered_json, rendered_markdown):
        print("brand retrieval eval canonical report drifted", file=sys.stderr)
        return 1
    print(
        "brand retrieval eval passed: "
        f"{aggregate.passed_count}/{aggregate.case_count}; "
        f"v3 recall@5={aggregate.structured_v3.macro_recall_at_5:.6f}; "
        f"v3 ndcg@5={aggregate.structured_v3.macro_ndcg_at_5:.6f}; "
        f"parent delta={aggregate.parent_diversity_delta:+.6f}; fact violations=0"
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
