from __future__ import annotations

from typing import Protocol

from app.domain.topic_rerank import TopicRerankModelResult, TopicRerankRequest


class TopicReranker(Protocol):
    async def rerank(self, request: TopicRerankRequest) -> TopicRerankModelResult: ...
