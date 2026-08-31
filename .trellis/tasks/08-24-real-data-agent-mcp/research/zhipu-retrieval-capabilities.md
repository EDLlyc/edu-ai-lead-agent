# Zhipu Retrieval Capabilities

## Verified APIs

- Structured output: OpenAI-compatible chat completions accept `response_format={"type":"json_object"}`. Official documentation: <https://docs.bigmodel.cn/cn/guide/capabilities/struct-output>
- Text reranking: `POST /paas/v4/rerank`, model `rerank`, bounded query/documents and `top_n`; documents can be omitted from the response. Official documentation: <https://docs.bigmodel.cn/api-reference/%E6%A8%A1%E5%9E%8B-api/%E6%96%87%E6%9C%AC%E9%87%8D%E6%8E%92%E5%BA%8F>

## Project Decision

- Reuse `Settings.ai_chat_model` (currently `glm-5.2`) for one-shot query planning with thinking disabled, deterministic sampling and strict JSON validation.
- Keep Zhipu `embedding-3` only for the existing governance event/article vector paths. Brand RAG uses the separately configured Alibaba multimodal identity.
- Add a dedicated `rerank` adapter over the same owned HTTP client. Validate candidate indexes, finite scores and response bounds before accepting the ranking.
- The planner emits at most one rewritten query and never invents events, institutions or claims. Invalid output, low lexical overlap, timeout or provider errors fall back to the original query.
- Rerank is optional enrichment. Any failure falls back to stable weighted RRF; evidence governance and brand audience/effective-date filters remain in PostgreSQL retrieval.

## Rejected Complexity

HyDE, iterative/self-reflective retrieval, GraphRAG, ColBERT, a new vector database and distributed result caching were rejected for this task. They would add operational and evaluation surface without making the interview story materially clearer than controlled rewrite, hybrid recall, RRF, rerank and measurable fallback behavior.
