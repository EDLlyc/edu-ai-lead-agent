from __future__ import annotations

import json
from typing import Literal, TypedDict
from uuid import UUID

from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph
from langgraph.types import Checkpointer

from app.application.ports.governance import (
    Clock,
    EmbeddingModel,
    EmbeddingRequest,
    FactualAnalysisPassage,
    FactualAnalysisRequest,
    GovernanceArtifactRepository,
    GovernanceRepository,
)
from app.application.services.governance_analysis import FactualAnalysisCoordinator
from app.domain.event_assignment import (
    EventArticleProfile,
    EventAssignmentDecision,
    EventAssignmentPolicy,
    decide_event_assignment,
)
from app.domain.governance_deduplication import (
    ExactDuplicateArtifact,
    select_exact_duplicate_canonical,
)
from app.domain.governance_entities import ClaimedGovernanceJob, GovernanceVersionBundle
from app.domain.governance_enums import EmbeddingPurpose, EventAssignmentOutcome
from app.domain.governance_normalization import normalize_and_segment, normalized_sha256
from app.domain.governance_pipeline import (
    AnalysisArtifact,
    EmbeddingArtifact,
    NormalizedArtifact,
    PersistedEventAssignment,
    StoredGovernanceCandidate,
)
from app.domain.governance_semantic import (
    SemanticArticle,
    SemanticDuplicatePolicy,
    decide_semantic_duplicate,
)


class GovernanceGraphState(TypedDict, total=False):
    """Checkpoint-safe state: identifiers, hashes, versions, statuses, and small results only."""

    job_id: UUID
    run_id: UUID
    candidate_id: UUID
    attempt_number: int
    lease_token: UUID
    input_content_hash: str
    idempotency_key: str
    version_bundle: dict[str, str | int]
    stage: str
    normalized_article_id: UUID
    requires_quarantine: bool
    exact_canonical_article_id: UUID
    analysis_article_id: UUID
    analysis_id: UUID
    exact_reuse_event_id: UUID
    near_duplicate_embedding_id: UUID
    semantic_relation_ids: tuple[UUID, ...]
    event_embedding_id: UUID
    recent_event_ids: tuple[UUID, ...]
    proposed_assignment_outcome: str
    proposed_event_id: UUID
    assignment_decision_id: UUID
    assignment_outcome: str
    event_id: UUID
    event_version_id: UUID
    source_diversity: int


CompiledGovernanceGraph = CompiledStateGraph[
    GovernanceGraphState,
    None,
    GovernanceGraphState,
    GovernanceGraphState,
]


def governance_graph_input(claimed: ClaimedGovernanceJob) -> GovernanceGraphState:
    return GovernanceGraphState(
        job_id=claimed.job_id,
        run_id=claimed.run_id,
        candidate_id=claimed.candidate_id,
        attempt_number=claimed.attempt_number,
        lease_token=claimed.lease_token,
        input_content_hash=claimed.input_content_hash,
        idempotency_key=claimed.idempotency_key,
        version_bundle=claimed.version_bundle.as_metadata(),
        stage="queued",
    )


def governance_graph_resume_claim(claimed: ClaimedGovernanceJob) -> GovernanceGraphState:
    """Refresh dynamic fencing fields before continuing a durable checkpoint."""

    return GovernanceGraphState(
        job_id=claimed.job_id,
        run_id=claimed.run_id,
        candidate_id=claimed.candidate_id,
        attempt_number=claimed.attempt_number,
        lease_token=claimed.lease_token,
        input_content_hash=claimed.input_content_hash,
        idempotency_key=claimed.idempotency_key,
        version_bundle=claimed.version_bundle.as_metadata(),
    )


def governance_thread_id(job_id: UUID) -> str:
    return f"governance-job:{job_id}"


def build_governance_graph(
    *,
    governance_repository: GovernanceRepository,
    artifact_repository: GovernanceArtifactRepository,
    analysis_coordinator: FactualAnalysisCoordinator,
    embedding_model: EmbeddingModel,
    clock: Clock,
    semantic_policy: SemanticDuplicatePolicy,
    event_policy: EventAssignmentPolicy,
    analysis_max_output_tokens: int,
    semantic_candidate_limit: int = 20,
    checkpointer: Checkpointer = None,
    interrupt_after: list[str] | None = None,
) -> CompiledGovernanceGraph:
    if analysis_max_output_tokens < 1 or semantic_candidate_limit < 1:
        raise ValueError("graph analysis and semantic candidate limits must be positive")

    async def record_stage(state: GovernanceGraphState, stage: str) -> ClaimedGovernanceJob:
        claimed = _claimed_job(state)
        await governance_repository.update_stage(claimed, stage=stage)
        return claimed

    async def load_candidate_node(state: GovernanceGraphState) -> GovernanceGraphState:
        claimed = await record_stage(state, "load_candidate")
        if semantic_policy.version != claimed.version_bundle.similarity_rule_version:
            raise ValueError("semantic policy does not match the claimed version bundle")
        if event_policy.version != claimed.version_bundle.event_assignment_version:
            raise ValueError("event policy does not match the claimed version bundle")
        await artifact_repository.load_candidate(claimed)
        return {"stage": "candidate-loaded"}

    async def synchronize_occurrences_node(
        state: GovernanceGraphState,
    ) -> GovernanceGraphState:
        claimed = await record_stage(state, "sync_source_occurrences")
        await governance_repository.synchronize_occurrences(claimed)
        return {"stage": "occurrences-synchronized"}

    async def normalize_node(state: GovernanceGraphState) -> GovernanceGraphState:
        claimed = await record_stage(state, "normalize_and_segment")
        candidate = await artifact_repository.load_candidate(claimed)
        document = normalize_and_segment(
            candidate_id=candidate.candidate_id,
            source_text=candidate.clean_text,
            normalization_version=claimed.version_bundle.normalization_version,
            passage_schema_version=claimed.version_bundle.passage_schema_version,
            input_content_hash=candidate.content_hash,
        )
        article = await artifact_repository.persist_normalized(
            claimed=claimed,
            document=document,
            language=candidate.language,
        )
        return {
            "stage": "normalized",
            "normalized_article_id": article.normalized_article_id,
            "requires_quarantine": document.requires_quarantine,
        }

    async def exact_duplicate_gate_node(
        state: GovernanceGraphState,
    ) -> GovernanceGraphState:
        await record_stage(state, "exact_duplicate_gate")
        claimed, candidate, article = await _load_current_article(state, artifact_repository)
        occurrences = await governance_repository.synchronize_occurrences(claimed)
        incoming = ExactDuplicateArtifact(
            normalized_article_id=article.normalized_article_id,
            candidate_id=article.candidate_id,
            source_id=candidate.source_id,
            normalized_hash=article.normalized_hash,
            input_content_hash=article.input_content_hash,
            canonical_url=candidate.canonical_url,
            source_item_id=candidate.source_item_id,
            first_fetched_at=candidate.first_fetched_at,
            occurrence_ids=tuple(occurrence.occurrence_id for occurrence in occurrences),
        )
        existing = await artifact_repository.find_exact_duplicates(
            claimed=claimed,
            article=article,
        )
        decision = select_exact_duplicate_canonical(incoming, existing)
        if decision is None:
            return {"stage": "exact-distinct"}
        await artifact_repository.persist_exact_duplicate_decision(
            claimed=claimed,
            incoming=incoming,
            decision=decision,
            policy_version=claimed.version_bundle.similarity_rule_version,
        )
        return {
            "stage": "exact-duplicate",
            "exact_canonical_article_id": decision.canonical.normalized_article_id,
        }

    def route_after_exact_gate(
        state: GovernanceGraphState,
    ) -> Literal["exact_reuse", "analyze", "terminal"]:
        if "exact_canonical_article_id" in state:
            return "exact_reuse"
        if state.get("requires_quarantine", False):
            return "terminal"
        return "analyze"

    async def exact_reuse_node(state: GovernanceGraphState) -> GovernanceGraphState:
        claimed = await record_stage(state, "reuse_existing_derivation")
        canonical_article_id = state["exact_canonical_article_id"]
        reuse = await artifact_repository.find_exact_reuse(
            claimed=claimed,
            canonical_article_id=canonical_article_id,
        )
        if reuse is None:
            return {"stage": "exact-reuse-miss"}
        update = GovernanceGraphState(
            stage="exact-analysis-reused",
            analysis_article_id=reuse.canonical_article_id,
            analysis_id=reuse.analysis_id,
        )
        if reuse.event_id is not None:
            update["exact_reuse_event_id"] = reuse.event_id
        return update

    def route_after_exact_reuse(
        state: GovernanceGraphState,
    ) -> Literal["reuse_event", "embed", "analyze", "terminal"]:
        if "exact_reuse_event_id" in state:
            return "reuse_event"
        if "analysis_article_id" in state:
            return "terminal" if state.get("requires_quarantine", False) else "embed"
        return "terminal" if state.get("requires_quarantine", False) else "analyze"

    async def analyze_node(state: GovernanceGraphState) -> GovernanceGraphState:
        await record_stage(state, "structured_factual_analysis")
        claimed, candidate, article = await _load_current_article(state, artifact_repository)
        analysis = await artifact_repository.load_analysis(
            claimed=claimed,
            normalized_article_id=article.normalized_article_id,
        )
        if analysis is None:
            request = FactualAnalysisRequest(
                candidate_id=candidate.candidate_id,
                title=candidate.title,
                published_at=candidate.published_at,
                language=candidate.language,
                passages=tuple(
                    FactualAnalysisPassage(
                        passage_id=passage.passage_id,
                        ordinal=passage.ordinal,
                        passage_hash=passage.passage_hash,
                        text=passage.text,
                    )
                    for passage in article.passages
                ),
                prompt_version=claimed.version_bundle.prompt_version,
                schema_version=claimed.version_bundle.analysis_schema_version,
                taxonomy_version=claimed.version_bundle.taxonomy_version,
                max_output_tokens=analysis_max_output_tokens,
            )
            result = await analysis_coordinator.analyze(request)
            analysis = await artifact_repository.persist_analysis(
                claimed=claimed,
                article=article,
                result=result,
                prompt_version=claimed.version_bundle.prompt_version,
                schema_version=claimed.version_bundle.analysis_schema_version,
                taxonomy_version=claimed.version_bundle.taxonomy_version,
            )
        return {
            "stage": "analysis-persisted",
            "analysis_article_id": article.normalized_article_id,
            "analysis_id": analysis.analysis_id,
        }

    async def near_duplicate_embedding_node(
        state: GovernanceGraphState,
    ) -> GovernanceGraphState:
        await record_stage(state, "embed_for_near_duplicate")
        claimed, candidate, article = await _load_current_article(state, artifact_repository)
        embedding_text = _near_duplicate_text(candidate, article)
        embedding = await _ensure_embedding(
            claimed=claimed,
            article=article,
            purpose=EmbeddingPurpose.NEAR_DUPLICATE,
            text=embedding_text,
            artifact_repository=artifact_repository,
            embedding_model=embedding_model,
        )
        return {
            "stage": "near-duplicate-embedded",
            "near_duplicate_embedding_id": embedding.embedding_id,
        }

    async def semantic_duplicate_node(state: GovernanceGraphState) -> GovernanceGraphState:
        await record_stage(state, "decide_near_duplicate")
        claimed, _, article = await _load_current_article(state, artifact_repository)
        embedding_text = _near_duplicate_text(
            await artifact_repository.load_candidate(claimed), article
        )
        embedding = await _require_embedding(
            claimed=claimed,
            article=article,
            purpose=EmbeddingPurpose.NEAR_DUPLICATE,
            input_hash=normalized_sha256(embedding_text),
            artifact_repository=artifact_repository,
        )
        candidates = await artifact_repository.find_semantic_candidates(
            claimed=claimed,
            article=article,
            embedding=embedding,
            limit=semantic_candidate_limit,
        )
        incoming = SemanticArticle(
            normalized_article_id=article.normalized_article_id,
            candidate_id=article.candidate_id,
            simhash_hex=article.simhash_hex,
            vector=embedding.vector,
        )
        decisions = tuple(
            decide_semantic_duplicate(
                incoming,
                SemanticArticle(
                    normalized_article_id=candidate.normalized_article_id,
                    candidate_id=candidate.candidate_id,
                    simhash_hex=candidate.simhash_hex,
                    vector=candidate.vector,
                ),
                semantic_policy,
            )
            for candidate in candidates
        )
        relation_ids = await artifact_repository.persist_semantic_decisions(
            claimed=claimed,
            decisions=decisions,
        )
        return {
            "stage": "semantic-decisions-persisted",
            "semantic_relation_ids": relation_ids,
        }

    async def event_signature_embedding_node(
        state: GovernanceGraphState,
    ) -> GovernanceGraphState:
        await record_stage(state, "build_and_embed_event_signature")
        claimed, candidate, article = await _load_current_article(state, artifact_repository)
        analysis = await _load_selected_analysis(state, claimed, artifact_repository)
        signature = _event_signature(candidate, analysis)
        embedding = await _ensure_embedding(
            claimed=claimed,
            article=article,
            purpose=EmbeddingPurpose.EVENT_ASSIGNMENT,
            text=signature,
            artifact_repository=artifact_repository,
            embedding_model=embedding_model,
        )
        return {
            "stage": "event-signature-embedded",
            "event_embedding_id": embedding.embedding_id,
        }

    async def retrieve_recent_events_node(
        state: GovernanceGraphState,
    ) -> GovernanceGraphState:
        claimed = await record_stage(state, "retrieve_recent_event_candidates")
        await _load_current_article(state, artifact_repository)
        incoming, embedding = await _load_event_inputs(state, claimed, artifact_repository)
        candidates = await artifact_repository.find_recent_event_candidates(
            claimed=claimed,
            incoming=incoming,
            embedding=embedding,
            policy=event_policy,
            now=clock.now(),
        )
        return {
            "stage": "recent-events-retrieved",
            "recent_event_ids": tuple(candidate.profile.event_id for candidate in candidates),
        }

    async def decide_event_assignment_node(
        state: GovernanceGraphState,
    ) -> GovernanceGraphState:
        claimed = await record_stage(state, "decide_event_assignment")
        incoming, embedding = await _load_event_inputs(state, claimed, artifact_repository)
        candidates = await artifact_repository.find_recent_event_candidates(
            claimed=claimed,
            incoming=incoming,
            embedding=embedding,
            policy=event_policy,
            now=clock.now(),
        )
        decision = decide_event_assignment(
            incoming,
            tuple(candidate.profile for candidate in candidates),
            event_policy,
        )
        update = GovernanceGraphState(
            stage="event-assignment-decided",
            proposed_assignment_outcome=decision.outcome.value,
        )
        if decision.selected_event_id is not None:
            update["proposed_event_id"] = decision.selected_event_id
        return update

    async def persist_event_assignment_node(
        state: GovernanceGraphState,
    ) -> GovernanceGraphState:
        claimed = await record_stage(state, "persist_event_assignment")
        incoming, embedding = await _load_event_inputs(state, claimed, artifact_repository)
        now = clock.now()
        candidates = await artifact_repository.find_recent_event_candidates(
            claimed=claimed,
            incoming=incoming,
            embedding=embedding,
            policy=event_policy,
            now=now,
        )
        decision = decide_event_assignment(
            incoming,
            tuple(candidate.profile for candidate in candidates),
            event_policy,
        )
        persisted = await artifact_repository.persist_event_assignment(
            claimed=claimed,
            incoming=incoming,
            decision=decision,
            policy=event_policy,
            now=now,
        )
        return _assignment_update(persisted)

    async def reuse_exact_event_node(state: GovernanceGraphState) -> GovernanceGraphState:
        await record_stage(state, "reuse_exact_event")
        claimed, candidate, article = await _load_current_article(state, artifact_repository)
        event_id = state["exact_reuse_event_id"]
        incoming = EventArticleProfile(
            normalized_article_id=article.normalized_article_id,
            title=candidate.title,
            vector=(1.0,),
            simhash_hex=article.simhash_hex,
            categories=frozenset(),
            entities=frozenset(),
            event_time=None,
            published_at=candidate.published_at or candidate.first_fetched_at,
        )
        decision = EventAssignmentDecision(
            outcome=EventAssignmentOutcome.ASSIGNED_EXISTING,
            selected_event_id=event_id,
            features=None,
            alternatives=(),
            policy_version=event_policy.version,
        )
        persisted = await artifact_repository.persist_event_assignment(
            claimed=claimed,
            incoming=incoming,
            decision=decision,
            policy=event_policy,
            now=clock.now(),
        )
        update = _assignment_update(persisted)
        update["stage"] = "exact-event-reused"
        return update

    async def terminal_node(state: GovernanceGraphState) -> GovernanceGraphState:
        await record_stage(state, "persist_terminal_projection")
        if state.get("requires_quarantine", False) and "assignment_outcome" not in state:
            return {"stage": "review-required-quarantine"}
        return {"stage": "terminal"}

    graph = StateGraph(GovernanceGraphState)
    graph.add_node("load_candidate", load_candidate_node)
    graph.add_node("sync_source_occurrences", synchronize_occurrences_node)
    graph.add_node("normalize_and_segment", normalize_node)
    graph.add_node("exact_duplicate_gate", exact_duplicate_gate_node)
    graph.add_node("reuse_existing_derivation", exact_reuse_node)
    graph.add_node("structured_factual_analysis", analyze_node)
    graph.add_node("embed_for_near_duplicate", near_duplicate_embedding_node)
    graph.add_node("decide_near_duplicate", semantic_duplicate_node)
    graph.add_node("build_and_embed_event_signature", event_signature_embedding_node)
    graph.add_node("retrieve_recent_event_candidates", retrieve_recent_events_node)
    graph.add_node("decide_event_assignment", decide_event_assignment_node)
    graph.add_node("persist_event_assignment", persist_event_assignment_node)
    graph.add_node("reuse_exact_event", reuse_exact_event_node)
    graph.add_node("persist_terminal_projection", terminal_node)

    graph.add_edge(START, "load_candidate")
    graph.add_edge("load_candidate", "sync_source_occurrences")
    graph.add_edge("sync_source_occurrences", "normalize_and_segment")
    graph.add_edge("normalize_and_segment", "exact_duplicate_gate")
    graph.add_conditional_edges(
        "exact_duplicate_gate",
        route_after_exact_gate,
        {
            "exact_reuse": "reuse_existing_derivation",
            "analyze": "structured_factual_analysis",
            "terminal": "persist_terminal_projection",
        },
    )
    graph.add_conditional_edges(
        "reuse_existing_derivation",
        route_after_exact_reuse,
        {
            "reuse_event": "reuse_exact_event",
            "embed": "embed_for_near_duplicate",
            "analyze": "structured_factual_analysis",
            "terminal": "persist_terminal_projection",
        },
    )
    graph.add_edge("structured_factual_analysis", "embed_for_near_duplicate")
    graph.add_edge("embed_for_near_duplicate", "decide_near_duplicate")
    graph.add_edge("decide_near_duplicate", "build_and_embed_event_signature")
    graph.add_edge("build_and_embed_event_signature", "retrieve_recent_event_candidates")
    graph.add_edge("retrieve_recent_event_candidates", "decide_event_assignment")
    graph.add_edge("decide_event_assignment", "persist_event_assignment")
    graph.add_edge("persist_event_assignment", "persist_terminal_projection")
    graph.add_edge("reuse_exact_event", "persist_terminal_projection")
    graph.add_edge("persist_terminal_projection", END)
    return graph.compile(
        checkpointer=checkpointer,
        interrupt_after=interrupt_after,
        name="governance-candidate-workflow",
    )


def _claimed_job(state: GovernanceGraphState) -> ClaimedGovernanceJob:
    return ClaimedGovernanceJob(
        job_id=state["job_id"],
        run_id=state["run_id"],
        candidate_id=state["candidate_id"],
        attempt_number=state["attempt_number"],
        lease_token=state["lease_token"],
        input_content_hash=state["input_content_hash"],
        idempotency_key=state["idempotency_key"],
        version_bundle=GovernanceVersionBundle.from_metadata(state["version_bundle"]),
    )


async def _load_current_article(
    state: GovernanceGraphState,
    artifact_repository: GovernanceArtifactRepository,
) -> tuple[ClaimedGovernanceJob, StoredGovernanceCandidate, NormalizedArtifact]:
    claimed = _claimed_job(state)
    candidate = await artifact_repository.load_candidate(claimed)
    document = normalize_and_segment(
        candidate_id=candidate.candidate_id,
        source_text=candidate.clean_text,
        normalization_version=claimed.version_bundle.normalization_version,
        passage_schema_version=claimed.version_bundle.passage_schema_version,
        input_content_hash=candidate.content_hash,
    )
    article = await artifact_repository.persist_normalized(
        claimed=claimed,
        document=document,
        language=candidate.language,
    )
    return claimed, candidate, article


def _near_duplicate_text(
    candidate: StoredGovernanceCandidate,
    article: NormalizedArtifact,
) -> str:
    return f"{candidate.title.strip()}\n{article.normalized_text}"


def _event_signature(
    candidate: StoredGovernanceCandidate,
    analysis: AnalysisArtifact,
) -> str:
    output = analysis.analysis
    payload = {
        "title": candidate.title.strip(),
        "summary": output.summary.text,
        "facts": [fact.text for fact in output.key_facts],
        "categories": sorted(assignment.category.value for assignment in output.categories),
        "entities": sorted(
            {
                f"{entity.entity_type.value}:{entity.canonical_name.casefold()}"
                for entity in output.entities
            }
        ),
        "event_time_start": (
            output.event_time_start.isoformat() if output.event_time_start is not None else None
        ),
    }
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True)


async def _ensure_embedding(
    *,
    claimed: ClaimedGovernanceJob,
    article: NormalizedArtifact,
    purpose: EmbeddingPurpose,
    text: str,
    artifact_repository: GovernanceArtifactRepository,
    embedding_model: EmbeddingModel,
) -> EmbeddingArtifact:
    input_hash = normalized_sha256(text)
    existing = await artifact_repository.load_embedding(
        claimed=claimed,
        normalized_article_id=article.normalized_article_id,
        purpose=purpose,
        input_hash=input_hash,
        input_version=claimed.version_bundle.embedding_input_version,
    )
    if existing is not None:
        return existing
    result = await embedding_model.embed(
        EmbeddingRequest(
            artifact_id=article.normalized_article_id,
            purpose=purpose,
            input_hash=input_hash,
            text=text,
            expected_dimensions=claimed.version_bundle.embedding_dimensions,
        )
    )
    return await artifact_repository.persist_embedding(
        claimed=claimed,
        normalized_article_id=article.normalized_article_id,
        purpose=purpose,
        input_hash=input_hash,
        input_version=claimed.version_bundle.embedding_input_version,
        result=result,
    )


async def _require_embedding(
    *,
    claimed: ClaimedGovernanceJob,
    article: NormalizedArtifact,
    purpose: EmbeddingPurpose,
    input_hash: str,
    artifact_repository: GovernanceArtifactRepository,
) -> EmbeddingArtifact:
    embedding = await artifact_repository.load_embedding(
        claimed=claimed,
        normalized_article_id=article.normalized_article_id,
        purpose=purpose,
        input_hash=input_hash,
        input_version=claimed.version_bundle.embedding_input_version,
    )
    if embedding is None:
        raise RuntimeError(f"required {purpose.value} embedding is missing")
    return embedding


async def _load_selected_analysis(
    state: GovernanceGraphState,
    claimed: ClaimedGovernanceJob,
    artifact_repository: GovernanceArtifactRepository,
) -> AnalysisArtifact:
    normalized_article_id = state.get("analysis_article_id", state["normalized_article_id"])
    analysis = await artifact_repository.load_analysis(
        claimed=claimed,
        normalized_article_id=normalized_article_id,
    )
    if analysis is None:
        raise RuntimeError("selected accepted analysis is missing")
    return analysis


async def _load_event_inputs(
    state: GovernanceGraphState,
    claimed: ClaimedGovernanceJob,
    artifact_repository: GovernanceArtifactRepository,
) -> tuple[EventArticleProfile, EmbeddingArtifact]:
    _, candidate, article = await _load_current_article(state, artifact_repository)
    analysis = await _load_selected_analysis(state, claimed, artifact_repository)
    signature = _event_signature(candidate, analysis)
    embedding = await _require_embedding(
        claimed=claimed,
        article=article,
        purpose=EmbeddingPurpose.EVENT_ASSIGNMENT,
        input_hash=normalized_sha256(signature),
        artifact_repository=artifact_repository,
    )
    output = analysis.analysis
    return (
        EventArticleProfile(
            normalized_article_id=article.normalized_article_id,
            title=candidate.title,
            vector=embedding.vector,
            simhash_hex=article.simhash_hex,
            categories=frozenset(assignment.category for assignment in output.categories),
            entities=frozenset(entity.canonical_name.casefold() for entity in output.entities),
            event_time=output.event_time_start,
            published_at=candidate.published_at or candidate.first_fetched_at,
        ),
        embedding,
    )


def _assignment_update(persisted: PersistedEventAssignment) -> GovernanceGraphState:
    update = GovernanceGraphState(
        stage="event-assignment-persisted",
        assignment_decision_id=persisted.decision_id,
        assignment_outcome=persisted.outcome.value,
        source_diversity=persisted.source_diversity,
    )
    if persisted.event_id is not None:
        update["event_id"] = persisted.event_id
    if persisted.event_version_id is not None:
        update["event_version_id"] = persisted.event_version_id
    return update
