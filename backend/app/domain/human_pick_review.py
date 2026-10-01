# ruff: noqa: RUF001
"""Operator edit of a held human pick's Moments copy: the hook sentence and the hashtags only.

The heading (🔎【小赛洞察】), the news headline and the source/link footer stay system-owned. An
edit is re-rendered with the template used for generated copy and re-checked with the same
deterministic rules (`validate_material_draft`, no model call). The LLM audit is not repeated;
the stored package records that the text is an operator edit of an audited draft.
"""

from __future__ import annotations

from dataclasses import dataclass

from pydantic import ValidationError

from app.domain.copy_generation import (
    HEADLINE_HOOK_COPY_RULE_VERSIONS,
    ActiveBrandContext,
    LockedTopicContext,
    validate_material_draft,
)
from app.schemas.copy_generation import (
    CopyIssue,
    MaterialDraft,
    extract_headline_hook,
    extract_trailing_hashtags,
    render_headline_hook_copy,
)

# Room for one sentence and its emoji; the 8-50 hanzi rule itself is the validator's warning.
OPERATOR_HOOK_MAX_CHARS = 120
OPERATOR_HASHTAG_MAX = 3
OPERATOR_HASHTAG_MAX_CHARS = 30


@dataclass(frozen=True, slots=True)
class CopyRevision:
    """The re-rendered copy (None if it could not be rendered) and every issue found."""

    copywriting: str | None
    hook: str
    hashtags: tuple[str, ...]
    issues: tuple[CopyIssue, ...]

    @property
    def passed(self) -> bool:
        return self.copywriting is not None and not any(
            issue.severity == "error" for issue in self.issues
        )


def _error(code: str, message: str) -> CopyIssue:
    return CopyIssue(code=code, message=message, severity="error", field="copywriting")


def revise_headline_hook_copy(
    draft: MaterialDraft,
    *,
    topic: LockedTopicContext,
    brand_context: tuple[ActiveBrandContext, ...],
    rule_version: str,
    hook: str,
    hashtags: tuple[str, ...],
) -> CopyRevision:
    """Replace the hook and hashtags of ``draft`` and re-check the whole copy."""

    if rule_version not in HEADLINE_HOOK_COPY_RULE_VERSIONS:
        raise ValueError("only headline-hook copy can be edited by the operator")
    if topic.title is None or not topic.evidence:
        raise ValueError("an edited copy needs the locked headline and its source")

    normalized_hook = " ".join(hook.split())
    tags = tuple(tag.strip() for tag in hashtags if tag.strip())
    if not normalized_hook:
        return CopyRevision(
            None, normalized_hook, tags, (_error("operator_hook_empty", "引导语不能为空"),)
        )
    if len(normalized_hook) > OPERATOR_HOOK_MAX_CHARS:
        return CopyRevision(
            None,
            normalized_hook,
            tags,
            (_error("operator_hook_too_long", f"引导语最多{OPERATOR_HOOK_MAX_CHARS}个字符"),),
        )
    if len(tags) > OPERATOR_HASHTAG_MAX or any(
        len(tag) > OPERATOR_HASHTAG_MAX_CHARS or " " in tag for tag in tags
    ):
        return CopyRevision(
            None,
            normalized_hook,
            tags,
            (_error("operator_hashtags_invalid", "话题标签最多3个，每个是一个以#开头的词"),),
        )

    evidence = topic.evidence[0]
    model_text = "\n".join((normalized_hook, " ".join(tags))) if tags else normalized_hook
    copywriting = render_headline_hook_copy(
        model_text,
        title=topic.title,
        source_name=evidence.source_name,
        source_url=evidence.source_url,
    )
    issues: list[CopyIssue] = []
    # The template drops lines that look like the heading, headline, source or tags; the
    # operator must see that instead of a silently different text.
    if extract_headline_hook(copywriting, title=topic.title) != normalized_hook:
        issues.append(
            _error(
                "operator_hook_not_rendered",
                "引导语不能是标题、来源、链接或话题标签，请只写一句给家长的话",
            )
        )
    if tags and extract_trailing_hashtags(copywriting) != tags:
        issues.append(_error("operator_hashtags_invalid", "话题标签最多3个，每个是一个以#开头的词"))
    try:
        revised = MaterialDraft.model_validate({**draft.model_dump(), "copywriting": copywriting})
    except ValidationError:
        issues.append(_error("operator_copy_too_long", "整条文案超过1200个字符"))
        return CopyRevision(None, normalized_hook, tags, tuple(issues))
    issues.extend(
        validate_material_draft(
            revised, topic=topic, brand_context=brand_context, rule_version=rule_version
        )
    )
    return CopyRevision(copywriting, normalized_hook, tags, tuple(issues))


__all__ = [
    "OPERATOR_HASHTAG_MAX",
    "OPERATOR_HASHTAG_MAX_CHARS",
    "OPERATOR_HOOK_MAX_CHARS",
    "CopyRevision",
    "revise_headline_hook_copy",
]
