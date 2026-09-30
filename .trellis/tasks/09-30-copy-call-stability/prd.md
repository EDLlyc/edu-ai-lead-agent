# Copy call stability and context length (2026-09-30)

Owner request: "先做第一个 — 模型调用的稳定性和上下文长度控制". Generator side only; the auditor side
(enumerated error codes, repair agent) belongs to the lean-context session.

## Production facts (slot copy runs, business dates 2026-08-31..09-29, 279 runs)

| Error code | Runs | Stories | What it really was |
|---|---|---|---|
| `copy_provider_unavailable` | 30 | – | 09-02..09-05 only: the worker ran without a configured generator (config gap, not the provider) |
| `provider_request_rejected` | 33 | 10 | Zhipu HTTP 400 code **1301** (content-safety filter); the provider code was not kept |
| `provider_input_limit` | 19 | 6 | generator prompt 39.6k–45.4k chars against the local 40,000-character limit |

- A failed story was picked again on the following days (one rejected story 7 days in a row, one
  over-limit story 7 times). `.14` already counts provider-rejected stories as used for the repeat
  window; over-limit stories were not.
- **Input limit, root cause**: `load_governed_event_evidence` returns one binding per governed fact
  (up to 24), and every binding of a long article repeats the same ~1,100-character passage as
  `exact_quote` (24 bindings, 1–4 distinct quotes). All 167 stories of the 30 days repeat quotes.
- **1301 is not deterministic**: the identical v27 prompt sent three times returned 200/400/400 for
  one story and 400/400/400 for another; both full prompts passed 3/3.

## Changes (branch `feat/copy-call-stability`, on mainline 4261d96)

1. Generator `moments-generator-v28-shared-quotes` = v27 + each distinct `exact_quote` written once.
   A repeated quote becomes `exact_quote_same_as: <first evidence_id>`; every binding keeps its own
   `evidence_id` and `governed_statement`. Safety net: evidence beyond 24,000 characters is dropped
   from the end (never below one item). Auditor stays v21. Long-image services accept v28.
2. `zhipu._post_json_with_retries`: reads the first 4 KB of a 400 body for the provider's error
   code. Code 1301 gets **one** identical retry (logged as `provider_content_filter_retry`); other
   codes and a second 1301 raise `ProviderRejectedError(provider_code)` at once.
3. Copy failures store `provider_error_code` in the attempt's `safe_metadata` and the log.
4. `evals/copy_quality` runner: a provider error on one topic is recorded and skipped instead of
   aborting the run (the 13:35 run lost 12 finished topics that way).

## Measurements

- Replay without model calls, 167 stories: generator EVIDENCE block mean 9,985 → 4,363 characters
  (−56%), median 8,917 → 3,535, max 35,114 → 14,536; estimated prompts over the limit 3 → 0; the
  budget dropped no item. The six historical over-limit stories: e.g. 43,591 → 15,023 characters.
- Seeded defects on production v26/v20 (27 topics, 243 defects): blocked 216 (89%), warned only 27
  (11%), missed 0; gaps are auditor policy (off-topic hook 16/25 warned only, paraphrased outcome
  promise 10/25) and were handed to the auditor session.
- Paired v27+v21 vs v28+v21: see `backend/evals/copy_cost/reports/2026-09-30-paired-shared-quotes.md`.

## Not done (needs the owner)

- A copy still rejected after the retry could be regenerated without BRAND; that drops the long
  image's 教学启发 material, so it is a product decision.
