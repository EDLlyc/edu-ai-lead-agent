from __future__ import annotations

import re
from collections.abc import Sequence
from datetime import date
from types import TracebackType
from typing import cast

import pytest
from app.application.ports.brand_knowledge import (
    BrandEmbeddingModel,
    BrandEmbeddingRequest,
    BrandEmbeddingResult,
)
from app.application.services.agent_tools import AgentToolFailure, build_agent_tool_registry
from app.domain.agent_workbench import AgentToolErrorCode
from app.infrastructure.db.agent_workbench import PostgresAgentKnowledgeReader
from app.schemas.agent_workbench import RetrieveBrandContextResult
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker


class _RowsResult:
    def __init__(self, rows: Sequence[tuple[object, ...]] = ()) -> None:
        self._rows = rows

    def tuples(self) -> Sequence[tuple[object, ...]]:
        return self._rows

    def one(self) -> tuple[object, ...]:
        if len(self._rows) != 1:
            raise AssertionError("test result expected exactly one row")
        return self._rows[0]


class _RecordingSession:
    def __init__(
        self,
        *,
        select_results: Sequence[Sequence[tuple[object, ...]]] = (),
    ) -> None:
        self.statements: list[str] = []
        self.rollback_count = 0
        self.exited = False
        self._select_results = list(select_results)

    async def __aenter__(self) -> _RecordingSession:
        return self

    async def __aexit__(
        self,
        _exception_type: type[BaseException] | None,
        _exception: BaseException | None,
        _traceback: TracebackType | None,
    ) -> None:
        self.exited = True

    async def execute(self, statement: object) -> _RowsResult:
        rendered = str(statement)
        self.statements.append(rendered)
        rows = (
            self._select_results.pop(0)
            if rendered.lstrip().startswith("SELECT") and self._select_results
            else ()
        )
        return _RowsResult(rows)

    async def rollback(self) -> None:
        self.rollback_count += 1


class _SessionFactory:
    def __init__(self, session: _RecordingSession) -> None:
        self._session = session

    def __call__(self) -> _RecordingSession:
        return self._session


@pytest.mark.asyncio
async def test_postgres_evidence_search_is_bounded_governed_and_read_only() -> None:
    session = _RecordingSession()
    reader = PostgresAgentKnowledgeReader(
        cast(async_sessionmaker[AsyncSession], _SessionFactory(session)),
        brand_embeddings=cast(BrandEmbeddingModel, object()),
        brand_retrieval_version="brand-hybrid-rrf-v3-parent-diverse",
    )

    records = await reader.search_evidence(
        query="人工智能教育",
        limit=3,
        candidate_id=None,
    )

    assert records == ()
    assert session.statements[:2] == [
        "SET TRANSACTION READ ONLY",
        "SET LOCAL statement_timeout = '4500ms'",
    ]
    search_statement = session.statements[2]
    assert search_statement.lstrip().startswith("SELECT DISTINCT")
    assert "websearch_to_tsquery" in search_statement
    assert "event_clusters.current_version_id" in search_statement
    assert "event_memberships.policy_version" not in search_statement
    assert "candidate_analyses.status" in search_statement
    assert "evidence_bindings.validated" in search_statement
    assert "article_occurrences.trust_tier" in search_statement
    assert " LIMIT " in search_statement
    assert re.search(r"\b(?:INSERT|UPDATE|DELETE)\b", search_statement, re.IGNORECASE) is None
    assert session.rollback_count == 1
    assert session.exited is True


class _MismatchedBrandEmbedding:
    async def embed_brand(self, _request: BrandEmbeddingRequest) -> BrandEmbeddingResult:
        return BrandEmbeddingResult(
            vector=(1.0,) * 2_048,
            provider="query-provider",
            model="query-model",
            request_fingerprint="fixture-fingerprint",
            provider_request_id=None,
        )


@pytest.mark.asyncio
async def test_brand_embedding_identity_mismatch_is_typed_unavailable() -> None:
    session = _RecordingSession(
        select_results=(((True, False),),),
    )
    reader = PostgresAgentKnowledgeReader(
        cast(async_sessionmaker[AsyncSession], _SessionFactory(session)),
        brand_embeddings=_MismatchedBrandEmbedding(),
        brand_retrieval_version="brand-hybrid-rrf-v3-parent-diverse",
    )
    registry = build_agent_tool_registry(reader)

    with pytest.raises(AgentToolFailure) as unavailable:
        await registry.invoke(
            "retrieve_brand_context",
            {
                "query": "家长沟通",
                "valid_on": date(2026, 8, 16).isoformat(),
                "audience": "parents",
                "document_kinds": [],
                "limit": 3,
            },
        )

    assert unavailable.value.code is AgentToolErrorCode.UNAVAILABLE
    assert len(session.statements) == 3
    assert session.statements[-1].count("EXISTS") == 2
    assert "brand_document_versions.embedding_provider" in session.statements[-1]
    assert "brand_document_versions.embedding_model" in session.statements[-1]
    assert session.rollback_count == 1
    assert session.exited is True


@pytest.mark.asyncio
async def test_brand_embedding_identity_match_continues_to_bounded_retrieval() -> None:
    session = _RecordingSession(select_results=(((True, True),),))
    reader = PostgresAgentKnowledgeReader(
        cast(async_sessionmaker[AsyncSession], _SessionFactory(session)),
        brand_embeddings=_MismatchedBrandEmbedding(),
        brand_retrieval_version="brand-hybrid-rrf-v3-parent-diverse",
    )
    registry = build_agent_tool_registry(reader)

    result = cast(
        RetrieveBrandContextResult,
        await registry.invoke(
            "retrieve_brand_context",
            {
                "query": "家长沟通",
                "valid_on": date(2026, 8, 16).isoformat(),
                "audience": "parents",
                "document_kinds": [],
                "limit": 3,
            },
        ),
    )

    assert result.items == ()
    assert len(session.statements) == 5
    assert session.statements[-2].lstrip().startswith("SELECT")
    assert session.statements[-1].lstrip().startswith("SELECT")
    assert session.rollback_count == 1
    assert session.exited is True
