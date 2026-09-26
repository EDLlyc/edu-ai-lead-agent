from __future__ import annotations

# ruff: noqa: RUF001 -- Exact Chinese footer and article punctuation are test data.
from copy import deepcopy
from uuid import UUID

import pytest
from app.domain.news_infographic import (
    InfographicInputError,
    build_private_input_bundle,
    validate_input_bundle,
    validate_package_snapshot,
)

PACKAGE_ID = "11111111-1111-4111-8111-111111111111"
RUN_ID = "22222222-2222-4222-8222-222222222222"
EVIDENCE_ID = "33333333-3333-4333-8333-333333333333"
BRAND_ID = "44444444-4444-4444-8444-444444444444"
URL = "http://www.moe.gov.cn/example/202608/story.html"


def package_payload() -> dict[str, object]:
    return {
        "id": PACKAGE_ID,
        "copy_generation_run_id": RUN_ID,
        "status": "awaiting_manual_use",
        "review_status": "pending",
        "package_version": 1,
        "topic": {
            "decision_kind": "selected",
            "selected_event_id": "55555555-5555-4555-8555-555555555555",
            "selected_event_version_id": "66666666-6666-4666-8666-666666666666",
            "business_date": "2026-08-07",
            "title": "科学课里的动手探究",
            "summary": "教育新闻与科学探究有关。",
        },
        "copy": {
            "draft_version_id": "77777777-7777-4777-8777-777777777777",
            "version": 2,
            "copywriting": (
                "小赛洞察：教育部介绍科学课探究。\n"
                f"新闻来源：教育部科学新闻\n原文链接：{URL}\n#赛先生科学"
            ),
            "prompt_version": "moments-generator-v18",
            "rule_version": "copy-rules-v18",
            "claims": [
                {
                    "claim_id": "fact-1",
                    "kind": "external_fact",
                    "text": "教育部介绍科学课探究。",
                    "evidence_ids": [EVIDENCE_ID],
                    "brand_chunk_ids": [],
                },
                {
                    "claim_id": "brand-1",
                    "kind": "brand_statement",
                    "text": "赛先生鼓励孩子提问。",
                    "evidence_ids": [],
                    "brand_chunk_ids": [BRAND_ID],
                },
            ],
        },
        "sources": [
            {
                "claim_id": "fact-1",
                "claim_text": "教育部介绍科学课探究。",
                "evidence_binding_id": EVIDENCE_ID,
                "candidate_id": "88888888-8888-4888-8888-888888888888",
                "passage_id": "99999999-9999-4999-8999-999999999999",
                "occurrence_id": "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
                "snapshot_id": "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb",
                "source_url": URL,
                "source_tier": "A",
                "published_at": "2026-08-04T16:00:00+08:00",
                "exact_quote": "教育部介绍科学课探究。",
            }
        ],
        "brand_bindings": [
            {
                "claim_id": "brand-1",
                "claim_text": "赛先生鼓励孩子提问。",
                "brand_chunk_id": BRAND_ID,
                "document_id": "cccccccc-cccc-4ccc-8ccc-cccccccccccc",
                "version_id": "dddddddd-dddd-4ddd-8ddd-dddddddddddd",
                "document_title": "品牌原始资料",
                "document_kind": "positioning",
                "text": "通过提问引导孩子拆解问题。",
                "private_path": "/private/do-not-export.pdf",
            }
        ],
        "validation": {"passed": True, "result_fingerprint": "a" * 64},
        "audit": {"accepted": True, "result_fingerprint": "b" * 64},
        "image": {"status": "failed", "private_object_key": "secret/object"},
    }


def test_freeze_preserves_original_date_and_excludes_private_response_fields() -> None:
    case = validate_package_snapshot(package_payload(), expected_package_id=UUID(PACKAGE_ID))
    assert case.business_date.isoformat() == "2026-08-07"
    assert case.source_date.isoformat() == "2026-08-04"
    assert case.source_url == URL
    assert case.source_footer.endswith(URL)
    assert case.package_status == "awaiting_manual_use"
    assert case.fingerprint == validate_package_snapshot(package_payload()).fingerprint

    bundle = build_private_input_bundle((case,))
    serialized = str(bundle)
    assert "private_path" not in serialized
    assert "private_object_key" not in serialized
    assert validate_input_bundle(bundle) == (case,)
    public = str(case.public_projection())
    assert "通过提问" not in public
    assert "exact_quote" not in public


@pytest.mark.parametrize(
    ("change", "expected"),
    [
        (lambda p: p["topic"].update(decision_kind="no_topic"), "not selected"),
        (lambda p: p["validation"].update(passed=False), "validation"),
        (lambda p: p["audit"].update(accepted=False), "validation"),
        (lambda p: p["copy"].update(copywriting="正文没有来源页脚"), "footer"),
        (lambda p: p["sources"][0].update(source_url="http://127.0.0.1/a"), "invalid"),
        (lambda p: p["copy"]["claims"][0].update(evidence_ids=[]), "invalid"),
        (lambda p: p["copy"]["claims"][1].update(brand_chunk_ids=[]), "invalid"),
        (lambda p: p["topic"].update(selected_event_version_id=None), "invalid"),
    ],
)
def test_incomplete_or_unsafe_package_stops_before_generation(
    change: object, expected: str
) -> None:
    payload = deepcopy(package_payload())
    change(payload)  # type: ignore[operator]
    with pytest.raises(InfographicInputError, match=expected):
        validate_package_snapshot(payload)


def test_bundle_rejects_tampered_binding_and_repeated_package() -> None:
    case = validate_package_snapshot(package_payload())
    bundle = build_private_input_bundle((case,))
    broken = deepcopy(bundle)
    broken["cases"][0]["claims"][0]["evidence_ids"] = [BRAND_ID]
    with pytest.raises(InfographicInputError, match="failed validation"):
        validate_input_bundle(broken)
    repeated = {"schema_version": bundle["schema_version"], "cases": bundle["cases"] * 2}
    with pytest.raises(InfographicInputError, match="repeats a package"):
        validate_input_bundle(repeated)
