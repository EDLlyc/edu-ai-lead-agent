"""Deterministic AB/BA order control, consensus, and eligible-subset coverage."""

from __future__ import annotations

from collections import Counter
from collections.abc import Mapping, Sequence

from .models import (
    CanonicalChoice,
    EligibleSubsetCoverage,
    JudgeVote,
    OrderControlledVote,
    OrderControlStatus,
    PanelConsensus,
    PresentationOrder,
    VoteProfile,
)


def resolve_order_control(
    *,
    evaluator_model_ref: str,
    pair_ref: str,
    case_ref: str,
    repeat_index: int,
    vote_profile: VoteProfile,
    ab_vote: JudgeVote | None,
    ba_vote: JudgeVote | None,
) -> OrderControlledVote:
    """Map both presentations to canonical arms and reject any position-dependent result."""

    for vote, expected_order in (
        (ab_vote, PresentationOrder.AB),
        (ba_vote, PresentationOrder.BA),
    ):
        if vote is not None and (
            vote.evaluator_model_ref != evaluator_model_ref
            or vote.pair_ref != pair_ref
            or vote.case_ref != case_ref
            or vote.repeat_index != repeat_index
            or vote.vote_profile is not vote_profile
            or vote.presentation_order is not expected_order
        ):
            raise ValueError("vote does not belong to the requested AB/BA cell")
    if ab_vote is None or ba_vote is None:
        return OrderControlledVote(
            evaluator_model_ref=evaluator_model_ref,
            pair_ref=pair_ref,
            case_ref=case_ref,
            repeat_index=repeat_index,
            vote_profile=vote_profile,
            ab_attempt_ref=None if ab_vote is None else ab_vote.attempt_ref,
            ba_attempt_ref=None if ba_vote is None else ba_vote.attempt_ref,
            canonical_choice=CanonicalChoice.UNRESOLVED,
            status=OrderControlStatus.INCOMPLETE,
        )
    text_equivalent = (
        ab_vote.canonical_choice is ba_vote.canonical_choice
        and ab_vote.issue_codes == ba_vote.issue_codes
    )
    arm_equivalent = (
        text_equivalent
        and ab_vote.canonical_first_verdict == ba_vote.canonical_first_verdict
        and ab_vote.canonical_second_verdict == ba_vote.canonical_second_verdict
    )
    equivalent = text_equivalent if vote_profile is VoteProfile.TEXT_PAIR else arm_equivalent
    if not equivalent:
        return OrderControlledVote(
            evaluator_model_ref=evaluator_model_ref,
            pair_ref=pair_ref,
            case_ref=case_ref,
            repeat_index=repeat_index,
            vote_profile=vote_profile,
            ab_attempt_ref=ab_vote.attempt_ref,
            ba_attempt_ref=ba_vote.attempt_ref,
            canonical_choice=CanonicalChoice.UNRESOLVED,
            status=OrderControlStatus.POSITION_CONFLICT,
        )
    if ab_vote.canonical_choice is CanonicalChoice.ABSTAIN:
        return OrderControlledVote(
            evaluator_model_ref=evaluator_model_ref,
            pair_ref=pair_ref,
            case_ref=case_ref,
            repeat_index=repeat_index,
            vote_profile=vote_profile,
            ab_attempt_ref=ab_vote.attempt_ref,
            ba_attempt_ref=ba_vote.attempt_ref,
            canonical_choice=CanonicalChoice.ABSTAIN,
            canonical_first_verdict=ab_vote.canonical_first_verdict,
            canonical_second_verdict=ab_vote.canonical_second_verdict,
            status=OrderControlStatus.ABSTAINED,
        )
    return OrderControlledVote(
        evaluator_model_ref=evaluator_model_ref,
        pair_ref=pair_ref,
        case_ref=case_ref,
        repeat_index=repeat_index,
        vote_profile=vote_profile,
        ab_attempt_ref=ab_vote.attempt_ref,
        ba_attempt_ref=ba_vote.attempt_ref,
        canonical_choice=ab_vote.canonical_choice,
        canonical_first_verdict=ab_vote.canonical_first_verdict,
        canonical_second_verdict=ab_vote.canonical_second_verdict,
        status=OrderControlStatus.CONSISTENT,
    )


def build_consensus(
    votes: Sequence[OrderControlledVote],
    *,
    target_model_ref: str | None,
    quorum: int = 2,
) -> PanelConsensus:
    """Build deterministic majority consensus after excluding the target model itself."""

    if not votes:
        raise ValueError("consensus requires at least one model vote")
    first = votes[0]
    if any(
        (vote.pair_ref, vote.case_ref, vote.repeat_index, vote.vote_profile)
        != (first.pair_ref, first.case_ref, first.repeat_index, first.vote_profile)
        for vote in votes
    ):
        raise ValueError("consensus votes must belong to one case/repeat/profile cell")
    refs = tuple(vote.evaluator_model_ref for vote in votes)
    if len(refs) != len(set(refs)):
        raise ValueError("consensus cannot contain duplicate evaluator models")
    excluded = tuple(
        sorted(
            vote.evaluator_model_ref
            for vote in votes
            if vote.evaluator_model_ref == target_model_ref
        )
    )
    members = tuple(
        sorted(
            (vote for vote in votes if vote.evaluator_model_ref != target_model_ref),
            key=lambda vote: vote.evaluator_model_ref,
        )
    )
    if not members:
        raise ValueError("target exclusion removed every consensus member")
    eligible = tuple(vote for vote in members if vote.status is OrderControlStatus.CONSISTENT)
    counts = Counter(vote.canonical_choice for vote in eligible)
    winners = tuple(sorted((choice for choice, count in counts.items() if count >= quorum)))
    if len(winners) == 1:
        consensus_choice = winners[0]
        supporters = tuple(
            sorted(
                vote.evaluator_model_ref
                for vote in eligible
                if vote.canonical_choice is consensus_choice
            )
        )
    else:
        consensus_choice = CanonicalChoice.UNRESOLVED
        supporters = ()
    return PanelConsensus(
        schema_version="model-panel-consensus-v1",
        pair_ref=first.pair_ref,
        case_ref=first.case_ref,
        repeat_index=first.repeat_index,
        target_model_ref=target_model_ref,
        quorum=quorum,
        member_votes=members,
        excluded_model_refs=excluded,
        consensus_choice=consensus_choice,
        supporting_models=supporters,
        eligible_vote_count=len(eligible),
        abstention_count=sum(vote.status is OrderControlStatus.ABSTAINED for vote in members),
        position_conflict_count=sum(
            vote.status is OrderControlStatus.POSITION_CONFLICT for vote in members
        ),
        incomplete_count=sum(vote.status is OrderControlStatus.INCOMPLETE for vote in members),
    )


def eligible_common_subset(
    votes_by_case: Mapping[str, Sequence[OrderControlledVote]],
    *,
    required_model_refs: Sequence[str],
) -> EligibleSubsetCoverage:
    """Return the exact common order-consistent subset eligible for panel agreement/κ."""

    required = tuple(sorted(set(required_model_refs)))
    if len(required) < 2 or len(required) != len(tuple(required_model_refs)):
        raise ValueError("eligible-subset models must be unique and include at least two models")
    total = tuple(sorted(votes_by_case))
    if not total:
        raise ValueError("eligible-subset coverage requires at least one case")
    eligible: list[str] = []
    for case_ref in total:
        by_model: dict[str, OrderControlledVote] = {}
        for vote in votes_by_case[case_ref]:
            if vote.case_ref != case_ref or vote.evaluator_model_ref in by_model:
                raise ValueError("eligible-subset votes contain a mismatched or duplicate cell")
            by_model[vote.evaluator_model_ref] = vote
        cells = {
            (vote.pair_ref, vote.repeat_index, vote.vote_profile) for vote in by_model.values()
        }
        if len(cells) > 1:
            raise ValueError("eligible-subset models must refer to one comparable cell")
        if all(
            model_ref in by_model and by_model[model_ref].status is OrderControlStatus.CONSISTENT
            for model_ref in required
        ):
            eligible.append(case_ref)
    return EligibleSubsetCoverage(
        required_model_refs=required,
        total_case_refs=total,
        eligible_case_refs=tuple(eligible),
        eligible_case_count=len(eligible),
        total_case_count=len(total),
        coverage=len(eligible) / len(total),
    )


def repeat_is_consistent(
    first: OrderControlledVote,
    repeated: OrderControlledVote,
) -> bool:
    """Compare two declared repeats without discarding their separate repeat identities."""

    if (
        first.evaluator_model_ref != repeated.evaluator_model_ref
        or first.case_ref != repeated.case_ref
        or first.pair_ref != repeated.pair_ref
        or first.vote_profile is not repeated.vote_profile
        or first.repeat_index == repeated.repeat_index
    ):
        raise ValueError("repeat comparison requires one model/pair with distinct repeat indexes")
    return (
        first.status is OrderControlStatus.CONSISTENT
        and repeated.status is OrderControlStatus.CONSISTENT
        and first.canonical_choice is repeated.canonical_choice
        and first.canonical_first_verdict == repeated.canonical_first_verdict
        and first.canonical_second_verdict == repeated.canonical_second_verdict
    )
