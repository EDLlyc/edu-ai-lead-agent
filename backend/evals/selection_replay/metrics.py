"""Pure metrics over one set of slot picks (production or a replayed rule variant)."""

from __future__ import annotations

from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import date
from uuid import UUID

from app.domain.content_slots import (
    _SAME_TOPIC_SIMILARITY,
    _SAME_TOPIC_TITLE_OVERLAP,
    TopicFingerprint,
    _cosine,
    _share_title_phrase,
)
from app.domain.topic_safety_signals import (
    evaluate_government_yaowen_topic,
    evaluate_negative_incident,
    evaluate_specialized_research,
)

REPEAT_WINDOW_DAYS = 14
SLOT_ORDER = ("morning", "noon", "evening")
SLOT_NAMES = {"morning": "早间", "noon": "午间", "evening": "晚间"}
GOV_YAOWEN_PRIORITY_REASON = "qualified_government_yaowen_priority"


@dataclass(frozen=True, slots=True)
class ReplayPick:
    business_date: date
    slot: str
    ordinal: int
    event_id: UUID
    title: str
    summary: str | None
    total: float
    passes_threshold: bool
    priority_reason: str | None
    embedding: tuple[float, ...] | None = field(default=None, repr=False, compare=False)

    @property
    def label(self) -> str:
        return f"{self.business_date:%m-%d} {SLOT_NAMES.get(self.slot, self.slot)}#{self.ordinal}"

    @property
    def fingerprint(self) -> TopicFingerprint:
        return TopicFingerprint(event_id=self.event_id, title=self.title, embedding=self.embedding)


def pick_order(pick: ReplayPick) -> tuple[date, int, int]:
    slot_index = SLOT_ORDER.index(pick.slot) if pick.slot in SLOT_ORDER else len(SLOT_ORDER)
    return pick.business_date, slot_index, pick.ordinal


MATCH_KINDS = ("same_event", "similar_article", "title_phrase")


def topic_match_kind(left: ReplayPick, right: ReplayPick) -> str | None:
    """Which clause of the production same-topic rule matched, strongest first."""

    if left.event_id == right.event_id:
        return "same_event"
    if (
        left.embedding is not None
        and right.embedding is not None
        and _cosine(left.embedding, right.embedding) >= _SAME_TOPIC_SIMILARITY
    ):
        return "similar_article"
    if _share_title_phrase(left.title, right.title, _SAME_TOPIC_TITLE_OVERLAP, strict=True):
        return "title_phrase"
    return None


def same_day_same_topic_pairs(picks: Sequence[ReplayPick]) -> list[tuple[str, str, str]]:
    """(match kind, left label + title, right label + title) for same-day pairs."""

    ordered = sorted(picks, key=pick_order)
    pairs = []
    for index, left in enumerate(ordered):
        for right in ordered[index + 1 :]:
            if right.business_date != left.business_date:
                continue
            kind = topic_match_kind(left, right)
            if kind is not None:
                pairs.append((kind, f"{left.label} {left.title}", f"{right.label} {right.title}"))
    return pairs


def cross_day_repeats(
    picks: Sequence[ReplayPick], window_days: int = REPEAT_WINDOW_DAYS
) -> list[tuple[str, str, str]]:
    """(match kind, earlier label + title, later label + title) for a story picked again."""

    ordered = sorted(picks, key=pick_order)
    repeats = []
    for index, later in enumerate(ordered):
        best: tuple[int, ReplayPick] | None = None
        for earlier in reversed(ordered[:index]):
            gap = (later.business_date - earlier.business_date).days
            if gap == 0:
                continue
            if gap > window_days:
                break
            kind = topic_match_kind(earlier, later)
            if kind is not None and (best is None or MATCH_KINDS.index(kind) < best[0]):
                best = (MATCH_KINDS.index(kind), earlier)
        if best is not None:
            kind_index, earlier = best
            repeats.append(
                (
                    MATCH_KINDS[kind_index],
                    f"{earlier.label} {earlier.title}",
                    f"{later.label} {later.title}",
                )
            )
    return repeats


def summarize(picks: Sequence[ReplayPick]) -> dict[str, object]:
    gov = [pick for pick in picks if pick.priority_reason == GOV_YAOWEN_PRIORITY_REASON]
    off_topic_gov = [
        pick for pick in gov if not evaluate_government_yaowen_topic(pick.title).matched
    ]
    negative = [
        pick for pick in picks if evaluate_negative_incident(pick.title, pick.summary).matched
    ]
    specialised = [pick for pick in picks if evaluate_specialized_research(pick.title).matched]
    below = [pick for pick in picks if not pick.passes_threshold]
    same_day = same_day_same_topic_pairs(picks)
    repeats = cross_day_repeats(picks)
    return {
        "picks": len(picks),
        "gov_yaowen_priority": len(gov),
        "gov_yaowen_priority_off_topic": [pick.label + " " + pick.title for pick in off_topic_gov],
        "education_policy": sum(
            1 for pick in picks if (pick.priority_reason or "").startswith("education_policy")
        ),
        "negative_incident": [pick.label + " " + pick.title for pick in negative],
        "specialised_research": [pick.label + " " + pick.title for pick in specialised],
        "below_threshold": len(below),
        "mean_total": round(sum(pick.total for pick in picks) / len(picks), 3) if picks else None,
        "same_day_same_topic": [f"[{kind}] {left} ~ {right}" for kind, left, right in same_day],
        "same_day_same_topic_by_kind": dict(Counter(kind for kind, _left, _right in same_day)),
        "cross_day_repeats": [f"[{kind}] {later} ← {earlier}" for kind, earlier, later in repeats],
        "cross_day_repeats_by_kind": dict(Counter(kind for kind, _earlier, _later in repeats)),
        "priority_reasons": dict(Counter(pick.priority_reason or "none" for pick in picks)),
    }


def slot_changes(
    baseline: Sequence[ReplayPick], candidate: Sequence[ReplayPick]
) -> list[tuple[str, list[str], list[str]]]:
    """Per (date, slot): titles only in the baseline, titles only in the candidate."""

    def by_slot(picks: Sequence[ReplayPick]) -> dict[tuple[date, str], set[str]]:
        grouped: dict[tuple[date, str], set[str]] = {}
        for pick in picks:
            grouped.setdefault((pick.business_date, pick.slot), set()).add(pick.title)
        return grouped

    left, right = by_slot(baseline), by_slot(candidate)
    changes = []
    for key in sorted(
        set(left) | set(right), key=lambda item: (item[0], SLOT_ORDER.index(item[1]))
    ):
        removed = sorted(left.get(key, set()) - right.get(key, set()))
        added = sorted(right.get(key, set()) - left.get(key, set()))
        if removed or added:
            label = f"{key[0]:%m-%d} {SLOT_NAMES.get(key[1], key[1])}"
            changes.append((label, removed, added))
    return changes
