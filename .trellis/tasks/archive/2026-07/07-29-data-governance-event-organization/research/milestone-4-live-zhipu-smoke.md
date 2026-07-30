# Milestone 4 Live Zhipu Workflow Acceptance

Date: 2026-07-30 (Asia/Shanghai)

## Scope and safety

The production-shaped governance command was run on one article already stored by the acquisition
capability. It exercised the durable run/job, LangGraph, factual analysis, two embedding purposes,
event assignment, persistence, and query projections. It did not fetch the source website.

The API key remained in the Git-ignored local `.env`. This record contains no credential,
authorization header, prompt/source body, raw provider response, hidden reasoning text, embedding
vector, or provider request ID.

## Accepted stored candidate

- Candidate: `0b274dab-b9ca-48c8-9262-531a3f0b07b5`
- Source: 光明网教育
- Title: 首届北京市中学生人形机器人足球赛总决赛举行
- Governance run: `c803c6b2-ffe2-4e9d-b42f-3bc5c7061703`
- Governance job: `0a5b3986-1fab-474a-83f7-70291aa1c4ee`
- Event: `49fab2df-c3a2-51e6-9279-3d976ab61636`

## Observable result

- Terminal job/result: `succeeded` / `created_new`
- Structured facts: `5`
- Normalized passages: `2`
- Preserved source occurrences: `1`
- Chat provider/model: Zhipu `glm-5.2`
- Embedding provider/model: Zhipu `embedding-3`
- Persisted embedding dimension: `2048`
- Prompt tokens: `3881`
- Completion tokens: `2079`
- Reasoning-token telemetry: `358`
- Total recorded model latency: `18314 ms`

The deterministic schema, taxonomy, date, passage-ID, and evidence-binding gates accepted the
result. The event policy found no sufficiently compatible recent event and therefore created one
new stable event and its first immutable projection version. The original source occurrence and
version bundle remain queryable through the governance APIs.

## Transport finding and permanent regression

The first live attempt revealed that a successful Zhipu HTTP 200 response may be gzip encoded and
can surface as an httpx `DecodingError` if automatic decoding handles a malformed or provider-
specific stream before the application applies its response bound.

The provider adapter now:

- requests only `Accept-Encoding: gzip`;
- reads the raw stream and bounds both compressed and decoded bytes;
- performs explicit gzip decoding and removes transport encoding/length headers before JSON
  parsing;
- rejects unsupported or malformed encodings as non-retryable `invalid_provider_output`;
- preserves compatibility with already-consumed `MockTransport` responses while still validating
  their declared encoding and length; and
- has chat, embedding, and malformed-gzip regression coverage.

After this fix, the same production-shaped workflow completed successfully with the safe result
above. This is bounded compatibility and functional acceptance evidence, not a statistically
representative live clustering benchmark; controlled fixtures remain the policy regression
baseline.
