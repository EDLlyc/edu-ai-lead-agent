# Zhipu Model Compatibility Probe

Date: 2026-07-29 (Asia/Shanghai)

## Scope and secret handling

The user authorized bounded live Zhipu calls and delegated model selection for the reviewed
governance capability. The API key is stored only in the Git-ignored local `.env` with mode `0600`.
This artifact contains no credential, authorization header, complete prompt, or raw embedding.

## Account-visible chat models

The official OpenAI-compatible `GET /models` endpoint succeeded for the configured account and
returned these chat model IDs:

- `glm-4.5`
- `glm-4.5-air`
- `glm-4.6`
- `glm-4.7`
- `glm-5`
- `glm-5-turbo`
- `glm-5.1`
- `glm-5.2`

## Structured-output probe

A minimal `glm-5.2` chat-completions request with `response_format.type=json_object` and
temperature zero returned valid JSON in `message.content` with the requested category slug.

Observed safe metadata:

- model: `glm-5.2`
- total tokens: 484
- prompt tokens: 88
- completion tokens: 396
- reasoning tokens: 374

The response also included provider-specific `reasoning_content`. The adapter must ignore and never
persist/log hidden reasoning; only the validated JSON `content` and safe usage/request metadata are
application inputs. The high reasoning-token share on a trivial probe reinforces the need for
token budgets, bounded concurrency, and later representative latency/cost measurement.

Current default chat selection: `glm-5.2` for the quality-first factual-analysis path requested by
the user. It remains configuration, not domain logic, so a measured latency/cost issue can switch
models through a new processing version.

## Embedding probe

The official embeddings endpoint accepted `model=embedding-3` for a two-character Chinese input.

Observed safe metadata:

- model: `embedding-3`
- vector dimension: 2048
- total/prompt tokens: 5

Current default embedding selection: `embedding-3`, fixed dimension `2048`. The database migration
and validated settings must encode this dimension and reject mismatched provider responses before
persistence. Store separate vectors for near-duplicate and event-signature purposes.

## Resulting configuration contract

- `AI_PLATFORM_BASE_URL=https://open.bigmodel.cn/api/paas/v4`
- `AI_CHAT_MODEL=glm-5.2`
- `AI_EMBEDDING_MODEL=embedding-3`
- `AI_EMBEDDING_DIMENSIONS=2048`

The key remains local secret configuration and is intentionally omitted.
