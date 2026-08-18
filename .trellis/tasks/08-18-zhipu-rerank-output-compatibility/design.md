# Design: Zhipu Topic-Rerank Output Compatibility

## 1. Boundary and versioning

Add a second explicit policy identity, tentatively
`topic-rerank-v2-zhipu-json-contract`, and make it the default in `Settings`, Compose, and
`.env.example`. Keep `topic-rerank-v1` supported for immutable historical snapshots.

The policy identity selects three coupled behaviors:

| Contract | v1 historical | v2 current |
| --- | --- | --- |
| Prompt | Existing prose-only prompt | Exact JSON shape, enum list, count/order/barrier rules |
| Request | Existing JSON mode payload | JSON mode + thinking disabled + sampling disabled |
| Content parsing | Exact JSON object only | Existing bounded one-object envelope scanner |

The domain config/request rejects unknown policy identities before the adapter sends HTTP. This
prevents an arbitrary configuration string from silently choosing an incompatible prompt/parser.

## 2. Prompt and provider payload

`build_topic_rerank_prompt()` becomes policy-aware. The v1 branch is retained as a named legacy
builder. The v2 system message embeds a compact example/schema describing only:

```json
{
  "items": [
    {
      "event_id": "candidate UUID",
      "ordinal": 1,
      "reason_codes": ["one to three allowlisted codes"],
      "explanation": "bounded explanation"
    }
  ]
}
```

The message also lists all seven literal reason-code values and requires exactly one item per
candidate, ordinals `1..N`, no additional keys, no Markdown, and no prose. Dynamic candidate data
stays only in the escaped `<candidate_data>` block; the system message never receives titles or
summaries.

For v2 the adapter sends:

```python
{
    "response_format": {"type": "json_object"},
    "thinking": {"type": "disabled"},
    "do_sample": False,
    "temperature": 0.0,
    "max_tokens": bounded_output_tokens,
}
```

This uses documented GLM-5.2 parameters without claiming server-side JSON-Schema enforcement.
Strict validation remains local.

## 3. Shared bounded JSON envelope

Move `ProviderJsonEnvelopeError`, `extract_provider_json_object()`, and its private scanner helpers
from the copy adapter into a provider-neutral `app.infrastructure.ai.provider_json` module. Keep the
copy adapter importing/re-exporting the same symbols so existing callers and tests remain stable.

The v2 rerank path feeds the extracted object to the existing strict Pydantic model. No field
coercion or semantic repair is added. The v1 branch calls strict `model_validate_json(content)`
directly, preserving replay behavior.

## 4. Failure projection and metrics

Add a topic-specific subclass of `InvalidProviderOutputError` carrying only validated safe metrics:

- prompt fingerprint;
- prompt/completion/reasoning token counts;
- elapsed latency;
- bounded internal issue codes and normalized validation `loc`/`type` entries.

Adapter failure stages:

1. response JSON / chat envelope invalid -> `topic_rerank_completion_invalid`;
2. content cannot yield one allowed JSON object -> `topic_rerank_json_envelope_invalid`;
3. strict object/UUID/item construction fails -> `topic_rerank_schema_invalid`.

`execute_topic_rerank()` catches that subclass before generic `ProviderError` and builds the normal
`invalid_provider_output` fallback while copying the safe metrics into `TopicRerankOutcome`.
No raw body or internal diagnostic is added to the public API or the rerank database row, so no
migration/OpenAPI change is needed. The one-time validation command may inspect the exception's
bounded issue codes directly.

## 5. Data flow

```text
eligible deterministic pool
  -> versioned prompt + JSON-mode request
  -> one provider operation
  -> bounded response bytes
  -> chat envelope validation
  -> v1 exact JSON OR v2 bounded one-object extraction
  -> strict Pydantic item schema
  -> UUID/item construction
  -> existing full-permutation + priority-barrier validator
  -> applied order

any failure
  -> typed safe diagnostic
  -> exact deterministic base order
  -> existing generic public failure code
```

No database session is held across the provider call, and no downstream selection or delivery rule
changes.

## 6. Compatibility and rollout

- No database migration: historical v1 snapshots remain valid and replay through the legacy path.
- New runs take v2 only through updated defaults or an explicit v2 environment value.
- The feature remains default-off. Updating the policy default does not call a provider by itself.
- No deployment or activation belongs to this task. A later deployment must independently verify
  server configuration and safe business timing.
- Rollback is application/config only: restore the prior code/default. Already persisted v2 runs
  require the v2-capable code for replay, so deployment rollback must not execute such runs under a
  v1-only image.

## 7. Validation strategy

Provider MockTransport tests must use independent provider-shaped fixtures rather than deriving
responses from the Pydantic output model. Cover pure JSON, one exact JSON fence, bounded prose,
unsafe envelopes, strict field/enum/type failures, output limits, payload parameters, and privacy.

Application tests prove the deterministic fallback copies safe metrics and never invokes a second
model call. Version tests prove v1 and v2 choose different request contracts without changing the
deterministic pool or downstream validators.

After local gates, run one manual synthetic call using the production adapter and
`max_attempts=1`. It is a validation observation, not a production activation.
