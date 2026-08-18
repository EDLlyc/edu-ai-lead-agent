# Result: Zhipu Topic-Rerank Output Compatibility

## Status

Implementation, independent review, local validation, and the single controlled live Zhipu
observation are complete. The observation used `max_attempts=1`, three synthetic candidates, and no
database session. No production service, database, feature flag, business run, delivery,
deployment, or push was changed.

## Delivered behavior

- Current defaults use `topic-rerank-v2-zhipu-json-contract`; literal `topic-rerank-v1` remains a
  supported historical prompt/payload/exact-parser branch, including the unchanged migration
  snapshot.
- Unknown policy identities fail in settings/domain request construction before transport.
- V2 sends JSON-object mode, `thinking.type=disabled`, `do_sample=false`, temperature zero, and the
  bounded output limit. Its system message freezes the exact object/item shape, all seven reason
  codes, complete count/permutation, integer ordinal, priority barrier, and no-Markdown/no-prose
  requirements while candidate text stays in the escaped data-only user block.
- The former copy-only one-object extractor now lives in the shared provider helper. Copy keeps an
  explicit compatibility re-export and unchanged behavior; rerank v2 uses the same bounded pure,
  exact-fence, or unique bounded-affix envelope set before strict schema/domain validation.
- Internal invalid-output stages are `topic_rerank_completion_invalid`,
  `topic_rerank_json_envelope_invalid`, and `topic_rerank_schema_invalid`. They carry only bounded
  normalized `loc`/`type`, safe fingerprints, usage, and latency. The durable/public category stays
  `invalid_provider_output`, performs no repair/judge call, and preserves the exact base order.
- Independent review additionally rejected request/config policy mismatches before transport and
  mapped provider-controlled unknown validation-location keys to `unknown`, preventing arbitrary
  completion text from entering safe diagnostics.

## Safe fingerprints and diagnostics

- Current disabled config fingerprint:
  `b9e7949aaf4c19642f8199e00c22937845221570bb0dffba09944507bfc2a5b0`
- Literal v1 disabled config fingerprint:
  `919acf47899b5068d71f050e3ef0afe1c1ac3877680ce9803994024a3ef2773e`
- Eval dataset SHA-256:
  `9905ac5ba1ef4fa6c7da790a67317a3458a7b2f1fcda616fb8844bbd30752288`
- Canonical JSON SHA-256:
  `8b7a55f4df1e9495b6ffff6fe33b583b65311ae71a4dfa79865c4a48b56bc47b`
- Canonical Markdown SHA-256:
  `de778bd8996277ebcc9f87ea5425497af15f7046ae2696a6794986fd04079d64`
- Root-cause/prevention record:
  `research/root-cause.md`.

## Gates completed

- Focused rerank/copy/provider suite after independent fixes: 159 passed.
- `make backend-check`: Ruff format, Ruff lint, strict mypy (169 source files), and 1,030 tests
  passed.
- `python -m evals.topic_rerank.runner --check`: 8/8 provider-free cases passed.
- `make api-contract-check`: OpenAPI and generated frontend client have no drift.
- `docker compose config --quiet`: passed.
- Alembic: single unchanged head `20260818_0022`.
- `git diff --check`: passed.
- Scoped credential-pattern and raw-content logging-sink scans: no matches.

## Live validation (root-owned)

- Attempt count: exactly one provider operation; adapter `max_attempts=1`; no retry.
- Input: three fixed synthetic candidate projections; no business news, database, worker, service,
  or production state.
- Outcome: `applied`; provider/model `zhipu` / `glm-5.2`.
- Base and final order: the same complete ordered UUID tuple
  `00000000-0000-4000-8000-000000000001`,
  `00000000-0000-4000-8000-000000000002`,
  `00000000-0000-4000-8000-000000000003`.
- Prompt fingerprint:
  `ed94de8e786ec0317866dec3f64e1bb8a75495d9e84df69ff1a8cef30e204a2d`.
- Usage: 1,026 prompt tokens, 200 completion tokens, 0 reasoning tokens.
- Latency: 14,324 ms.
- Returned reason codes were all allowlisted; the strict production adapter and full permutation /
  priority-barrier validator accepted the result. Raw prompt, explanations, completion, response
  body, headers, and credential were not printed or persisted.
- No second live call is authorized or required.
