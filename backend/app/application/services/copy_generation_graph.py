from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import TypedDict
from uuid import UUID

from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph
from langgraph.types import Checkpointer

from app.application.ports.copy_generation import ClaimedCopyGenerationJob


class CopyGenerationGraphState(TypedDict, total=False):
    """Checkpoint-safe state. Never add copy, prompt, evidence, or brand bodies."""

    job_id: str
    run_id: str
    attempt_number: int
    stage: str
    draft_version_id: str
    issue_codes: tuple[str, ...]


CompiledCopyGenerationGraph = CompiledStateGraph[
    CopyGenerationGraphState,
    None,
    CopyGenerationGraphState,
    CopyGenerationGraphState,
]


def copy_generation_graph_input(
    claimed: ClaimedCopyGenerationJob,
) -> CopyGenerationGraphState:
    return CopyGenerationGraphState(
        job_id=str(claimed.job_id),
        run_id=str(claimed.run_id),
        attempt_number=claimed.attempt_number,
        stage="claimed",
        issue_codes=(),
    )


def copy_generation_thread_id(job_id: UUID) -> str:
    return f"copy-generation-job:{job_id}"


def build_copy_generation_graph(
    *,
    execute_workflow: Callable[[CopyGenerationGraphState], Awaitable[None]],
    checkpointer: Checkpointer = None,
) -> CompiledCopyGenerationGraph:
    async def orchestrate_node(
        state: CopyGenerationGraphState,
    ) -> CopyGenerationGraphState:
        await execute_workflow(state)
        return {"stage": "workflow-finished"}

    builder = StateGraph(CopyGenerationGraphState)
    builder.add_node("orchestrate", orchestrate_node)
    builder.add_edge(START, "orchestrate")
    builder.add_edge("orchestrate", END)
    return builder.compile(checkpointer=checkpointer)
