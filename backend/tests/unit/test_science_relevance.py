from app.domain.science_relevance import (
    SCIENCE_CONTENT_CHARACTER_LIMIT,
    SCIENCE_RELEVANCE_RULE_VERSION,
    evaluate_moe_science_relevance,
)


def test_title_match_is_audited_without_body_match() -> None:
    result = evaluate_moe_science_relevance("科学教育行动", "学校开展阅读活动。")

    assert result.is_relevant is True
    assert result.rule_version == SCIENCE_RELEVANCE_RULE_VERSION
    assert result.matched_title_terms == ("科学", "科学教育")
    assert result.matched_content_terms == ()
    assert result.matched_terms == ("科学", "科学教育")
    assert result.content_characters_considered == len("学校开展阅读活动。")
    assert result.content_truncated is False


def test_body_match_is_relevant_when_title_is_neutral() -> None:
    result = evaluate_moe_science_relevance("工作动态", "组织机器人实验和科学探究活动。")

    assert result.is_relevant is True
    assert result.matched_title_terms == ()
    assert result.matched_content_terms == ("科学", "机器人", "实验", "科学探究", "探究")


def test_non_science_title_and_body_are_not_relevant() -> None:
    result = evaluate_moe_science_relevance("教育工作安排", "开展教师培训和校园管理工作。")

    assert result.is_relevant is False
    assert result.matched_terms == ()


def test_body_is_normalized_and_bounded() -> None:
    content = "普通内容。" * SCIENCE_CONTENT_CHARACTER_LIMIT + "人工智能"
    result = evaluate_moe_science_relevance("工作动态", content)

    assert result.is_relevant is False
    assert result.content_characters_considered == SCIENCE_CONTENT_CHARACTER_LIMIT
    assert result.content_truncated is True


def test_nfkc_and_casefold_match_full_width_ascii_term() -> None:
    result = evaluate_moe_science_relevance("人工智能", "推动ＡＩ教育和科技创新。")

    assert result.is_relevant is True
    assert "AI" in result.matched_content_terms
    assert "科技" in result.matched_content_terms
    assert "创新" in result.matched_content_terms
