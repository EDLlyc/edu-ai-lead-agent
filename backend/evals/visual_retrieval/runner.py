from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from app.domain.visual_assets import (
    AssetSelectionRequest,
    AssetSelector,
    VisualAsset,
    VisualAssetCatalog,
    VisualAssetKind,
    VisualAssetRole,
)
from app.domain.visual_retrieval import (
    VISUAL_EMBEDDING_INPUT_POLICY_VERSION,
    VISUAL_SELECTOR_VERSION,
)

ROOT = Path(__file__).resolve().parent
CASES_PATH = ROOT / "cases.v1.jsonl"
CANONICAL_PATH = ROOT / "canonical-report.json"


def _asset(name: str, topic: str) -> VisualAsset:
    digest = hashlib.sha256(name.encode()).hexdigest()
    return VisualAsset(
        asset_id=digest,
        relative_path=f"fixtures/{name}.png",
        filename=f"{name}.png",
        category="fixture",
        byte_size=100,
        media_type="image/png",
        width=10,
        height=10,
        has_alpha=True,
        asset_kind=VisualAssetKind.IDENTITY,
        characters=("xiao-sai",),
        roles=(VisualAssetRole.IDENTITY_REFERENCE,),
        topics=(topic,),
        priority=10,
        approved=True,
    )


def evaluate() -> dict[str, object]:
    body = CASES_PATH.read_bytes()
    cases = [json.loads(line) for line in body.decode().splitlines() if line.strip()]
    if len(cases) != 6 or len({case["case_id"] for case in cases}) != 6:
        raise ValueError("visual retrieval eval requires six unique cases")
    results: list[dict[str, object]] = []
    for case in cases:
        left = _asset(f"{case['case_id']}-left", case["left_topic"])
        right = _asset(f"{case['case_id']}-right", case["right_topic"])
        catalog = VisualAssetCatalog(
            schema_version="brand-visual-assets-v2",
            catalog_version="visual-eval-catalog-v1",
            assets=(left, right),
        )
        raw_scores = case["scores"]
        if raw_scores is None:
            selector = AssetSelector(catalog)
        else:
            selector = AssetSelector(
                catalog,
                selector_version=VISUAL_SELECTOR_VERSION,
                semantic_scores={
                    left.asset_id: float(raw_scores["left"]),
                    right.asset_id: float(raw_scores["right"]),
                },
            )
        selected = selector.select(
            AssetSelectionRequest(
                category=case["category"],
                characters=("xiao-sai",),
                reference_roles=(VisualAssetRole.IDENTITY_REFERENCE,),
            )
        ).selected_assets[0]
        expected = case["expected"]
        expected_id = {
            "left": left.asset_id,
            "right": right.asset_id,
            "stable": min(left.asset_id, right.asset_id),
        }[expected]
        results.append(
            {
                "case_id": case["case_id"],
                "passed": selected.asset_id == expected_id,
                "ranking_source": selected.ranking_source,
            }
        )
    return {
        "schema_version": "visual-retrieval-eval-report-v2",
        "input_policy_version": VISUAL_EMBEDDING_INPUT_POLICY_VERSION,
        "dataset_sha256": hashlib.sha256(body).hexdigest(),
        "case_count": len(results),
        "passed_count": sum(bool(item["passed"]) for item in results),
        "results": results,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    report = evaluate()
    if args.check:
        expected = json.loads(CANONICAL_PATH.read_text(encoding="utf-8"))
        if report != expected:
            print("visual retrieval eval canonical report drifted")
            return 1
    print(json.dumps(report, ensure_ascii=False, separators=(",", ":")))
    return 0 if report["passed_count"] == report["case_count"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
