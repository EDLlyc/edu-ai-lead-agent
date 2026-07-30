from dataclasses import replace
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from app.domain.governance_deduplication import (
    ExactDuplicateArtifact,
    exact_duplicate_reasons,
    select_exact_duplicate_canonical,
)
from app.domain.governance_enums import DuplicateRelationKind
from app.domain.governance_normalization import (
    normalize_and_segment,
    normalized_sha256,
    simhash64,
    simhash_distance,
)


def test_normalization_is_versioned_stable_and_preserves_source_offset_envelopes() -> None:
    candidate_id = UUID("11111111-1111-4111-8111-111111111111")
    source = (
        "  \uff21\uff29\u3000教育  政策\r\n\r\n"
        "教育部门发布人工智能课程指南, 要求学校完善教师培训。\n"
        "责任编辑\uff1a测试编辑\n"
        "机器人课程将于秋季开始。  "
    )
    first = normalize_and_segment(
        candidate_id=candidate_id,
        source_text=source,
        normalization_version="normalization-v1",
        passage_schema_version="passage-v1",
        max_passage_characters=200,
        min_passage_characters=20,
    )
    second = normalize_and_segment(
        candidate_id=candidate_id,
        source_text=source,
        normalization_version="normalization-v1",
        passage_schema_version="passage-v1",
        max_passage_characters=200,
        min_passage_characters=20,
    )

    assert first == second
    assert first.normalized_text.startswith("AI 教育 政策")
    assert "责任编辑" not in first.normalized_text
    assert first.boilerplate_lines_removed == 1
    assert first.normalized_hash == normalized_sha256(first.normalized_text)
    assert len(first.simhash_hex) == 16
    assert first.passages
    for passage in first.passages:
        assert 0 <= passage.source_start < passage.source_end <= len(source)
        assert len(passage.text) <= 200
        assert passage.passage_hash == normalized_sha256(passage.text)


def test_normalization_applies_complete_nfkc_across_source_character_boundaries() -> None:
    source = "\u1100\u1161 한국어, \uff76\uff9e, A\u030a, \ufb03 与人工智能教育资料。" * 12
    document = normalize_and_segment(
        candidate_id=uuid4(),
        source_text=source,
        normalization_version="normalization-v1",
        passage_schema_version="passage-v1",
        max_passage_characters=200,
        min_passage_characters=20,
    )

    assert document.normalized_text.startswith("가 한국어, ガ, Å, ffi")
    assert all(
        0 <= passage.source_start < passage.source_end <= len(source)
        for passage in document.passages
    )


def test_normalization_rejects_non_hex_input_content_hash() -> None:
    with pytest.raises(ValueError, match="lowercase SHA-256"):
        normalize_and_segment(
            candidate_id=uuid4(),
            source_text="人工智能教育资料正文。" * 20,
            normalization_version="normalization-v1",
            passage_schema_version="passage-v1",
            input_content_hash="g" * 64,
            max_passage_characters=200,
            min_passage_characters=20,
        )


def test_normalization_redacts_sensitive_values_and_quarantines_credentials() -> None:
    source = (
        "联系人邮箱 teacher@example.com, 电话 13812345678, "
        "身份证 11010519491231002X。\n"
        "调试残留 api_key=abcdefghijklmnop 不应进入模型。"
    )
    document = normalize_and_segment(
        candidate_id=uuid4(),
        source_text=source,
        normalization_version="normalization-v1",
        passage_schema_version="passage-v1",
        max_passage_characters=400,
    )

    assert "teacher@example.com" not in document.normalized_text
    assert "13812345678" not in document.normalized_text
    assert "11010519491231002X" not in document.normalized_text
    assert "abcdefghijklmnop" not in document.normalized_text
    assert "[REDACTED_EMAIL]" in document.normalized_text
    assert "[REDACTED_MOBILE]" in document.normalized_text
    assert "[REDACTED_NATIONAL_ID]" in document.normalized_text
    assert "[QUARANTINED_CREDENTIAL]" in document.normalized_text
    assert document.requires_quarantine is True
    assert {signal.kind for signal in document.sensitive_data_signals} == {
        "email",
        "mobile_phone",
        "national_id",
        "credential_material",
    }


def test_simhash_is_deterministic_and_validates_hex_inputs() -> None:
    first = simhash64("人工智能 教育 机器人 课程")
    second = simhash64("人工智能\n教育\n机器人\n课程")
    unrelated = simhash64("传统文化 艺术 展览")

    assert first == second
    assert simhash_distance(first, second) == 0
    assert simhash_distance(first, unrelated) > 0


def _artifact(
    *,
    candidate_id: UUID,
    article_id: UUID,
    source_id: UUID,
    normalized_hash: str,
    fetched_at: datetime,
    occurrence_id: UUID,
) -> ExactDuplicateArtifact:
    return ExactDuplicateArtifact(
        normalized_article_id=article_id,
        candidate_id=candidate_id,
        source_id=source_id,
        normalized_hash=normalized_hash,
        input_content_hash="b" * 64,
        canonical_url=f"https://example.invalid/{candidate_id}",
        source_item_id=str(candidate_id),
        first_fetched_at=fetched_at,
        occurrence_ids=(occurrence_id,),
    )


def test_exact_duplicate_selection_is_deterministic_and_preserves_all_occurrences() -> None:
    now = datetime(2026, 7, 29, tzinfo=UTC)
    shared_hash = "a" * 64
    older = _artifact(
        candidate_id=UUID("00000000-0000-4000-8000-000000000001"),
        article_id=UUID("10000000-0000-4000-8000-000000000001"),
        source_id=uuid4(),
        normalized_hash=shared_hash,
        fetched_at=now,
        occurrence_id=UUID("20000000-0000-4000-8000-000000000001"),
    )
    incoming = _artifact(
        candidate_id=UUID("00000000-0000-4000-8000-000000000002"),
        article_id=UUID("10000000-0000-4000-8000-000000000002"),
        source_id=uuid4(),
        normalized_hash=shared_hash,
        fetched_at=now + timedelta(minutes=5),
        occurrence_id=UUID("20000000-0000-4000-8000-000000000002"),
    )

    assert exact_duplicate_reasons(older, incoming) == (DuplicateRelationKind.SAME_CONTENT,)
    decision = select_exact_duplicate_canonical(incoming, (older,))

    assert decision is not None
    assert decision.canonical == older
    assert decision.duplicates == (incoming,)
    assert decision.relations[0].relation_kind is DuplicateRelationKind.SAME_CONTENT
    assert set(decision.occurrence_ids) == set(older.occurrence_ids + incoming.occurrence_ids)


def test_exact_duplicate_preserves_every_matching_deterministic_reason() -> None:
    now = datetime(2026, 7, 29, tzinfo=UTC)
    source_id = uuid4()
    older = _artifact(
        candidate_id=uuid4(),
        article_id=uuid4(),
        source_id=source_id,
        normalized_hash="a" * 64,
        fetched_at=now,
        occurrence_id=uuid4(),
    )
    incoming = replace(
        _artifact(
            candidate_id=uuid4(),
            article_id=uuid4(),
            source_id=source_id,
            normalized_hash="a" * 64,
            fetched_at=now + timedelta(minutes=1),
            occurrence_id=uuid4(),
        ),
        canonical_url=older.canonical_url,
        source_item_id=older.source_item_id,
    )

    expected = {
        DuplicateRelationKind.SAME_CONTENT,
        DuplicateRelationKind.SAME_URL,
        DuplicateRelationKind.SAME_SOURCE_ITEM,
    }
    assert set(exact_duplicate_reasons(older, incoming)) == expected
    decision = select_exact_duplicate_canonical(incoming, (older,))
    assert decision is not None
    assert {relation.relation_kind for relation in decision.relations} == expected


def test_exact_duplicate_artifact_rejects_non_hex_hashes() -> None:
    with pytest.raises(ValueError, match="lowercase SHA-256"):
        _artifact(
            candidate_id=uuid4(),
            article_id=uuid4(),
            source_id=uuid4(),
            normalized_hash="z" * 64,
            fetched_at=datetime(2026, 7, 29, tzinfo=UTC),
            occurrence_id=uuid4(),
        )


def test_distinct_content_and_source_identity_does_not_create_exact_duplicate() -> None:
    now = datetime(2026, 7, 29, tzinfo=UTC)
    first = _artifact(
        candidate_id=uuid4(),
        article_id=uuid4(),
        source_id=uuid4(),
        normalized_hash="a" * 64,
        fetched_at=now,
        occurrence_id=uuid4(),
    )
    second = _artifact(
        candidate_id=uuid4(),
        article_id=uuid4(),
        source_id=uuid4(),
        normalized_hash="c" * 64,
        fetched_at=now,
        occurrence_id=uuid4(),
    )

    assert select_exact_duplicate_canonical(second, (first,)) is None
