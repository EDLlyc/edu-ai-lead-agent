# ruff: noqa: RUF001
from __future__ import annotations

from dataclasses import replace

import pytest
from app.domain.human_pick_review import revise_headline_hook_copy
from app.schemas.copy_generation import extract_headline_hook, extract_trailing_hashtags
from test_copy_generation import _brand, _headline_hook_draft, _topic

RULES = "moments-rules-v13-headline-hook"
TITLE = "世界技能大赛标准引领职教课堂 技能人才培养提质进行时"
ORIGINAL_HOOK = "当职业教育的标准走进课堂，正好和孩子聊聊学东西到底该追求什么✨"
EDITED_HOOK = "技能比赛的标准走进课堂，周末可以和孩子一起动手做个小作品🔧"


def _revise(hook: str, hashtags: tuple[str, ...] = ("#赛先生科学", "#动手实践")):
    topic = replace(_topic(), title=TITLE)
    draft = _headline_hook_draft(topic, ORIGINAL_HOOK)
    revision = revise_headline_hook_copy(
        draft,
        topic=topic,
        brand_context=_brand(),
        rule_version=RULES,
        hook=hook,
        hashtags=hashtags,
    )
    return topic, draft, revision


def test_operator_edit_changes_only_the_hook_and_tags() -> None:
    _, draft, revision = _revise(f"  {EDITED_HOOK}\n")

    assert revision.passed, revision.issues
    assert revision.hook == EDITED_HOOK
    assert revision.copywriting is not None
    before, after = draft.copywriting.splitlines(), revision.copywriting.splitlines()
    # Heading, headline and source/link footer are the system's, byte for byte.
    assert after[:3] == before[:3]
    assert after[-3:-1] == before[-3:-1]
    assert extract_headline_hook(revision.copywriting, title=TITLE) == EDITED_HOOK
    assert extract_trailing_hashtags(revision.copywriting) == ("#赛先生科学", "#动手实践")
    assert not [issue for issue in revision.issues if issue.severity == "error"]


@pytest.mark.parametrize(
    ("hook", "code"),
    (
        # The same deterministic rules as generated copy.
        ("赛先生保证提分，快带孩子来体验这门课程吧✨", "prohibited_marketing"),
        ("这项研究让学习效率提升了300%，和孩子一起看看吧🔬", "unclaimed_external_fact"),
        # Operator-specific: the template would silently drop these lines.
        ("新闻来源：光明网教育", "operator_hook_not_rendered"),
        ("   ", "operator_hook_empty"),
        ("好" * 121, "operator_hook_too_long"),
    ),
)
def test_operator_edit_is_blocked_by_an_error(hook: str, code: str) -> None:
    _, _, revision = _revise(hook)

    assert not revision.passed
    assert code in {issue.code for issue in revision.issues if issue.severity == "error"}


@pytest.mark.parametrize(
    "hashtags",
    (
        ("#赛先生科学", "#一", "#二", "#三"),
        ("#赛先生科学", "科学 思维"),
    ),
)
def test_operator_edit_rejects_malformed_hashtags(hashtags: tuple[str, ...]) -> None:
    _, _, revision = _revise(EDITED_HOOK, hashtags)

    assert not revision.passed
    assert "operator_hashtags_invalid" in {issue.code for issue in revision.issues}


def test_a_short_hook_is_only_a_warning() -> None:
    _, _, revision = _revise("一起动手试试🔧")

    assert revision.passed
    assert "copy_length" in {issue.code for issue in revision.issues if issue.severity == "warning"}


def test_only_headline_hook_copy_can_be_edited() -> None:
    topic = replace(_topic(), title=TITLE)
    draft = _headline_hook_draft(topic, ORIGINAL_HOOK)

    with pytest.raises(ValueError, match="headline-hook"):
        revise_headline_hook_copy(
            draft,
            topic=topic,
            brand_context=_brand(),
            rule_version="moments-rules-v12-relaxed-superlatives",
            hook=EDITED_HOOK,
            hashtags=(),
        )
