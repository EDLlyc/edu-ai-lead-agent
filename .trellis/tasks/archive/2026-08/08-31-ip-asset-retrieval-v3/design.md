# IP 图片检索 V3：技术设计

## 1. Retrieval architecture

```text
current turn + explicit filters
  -> bounded metadata candidates -> stable metadata rank
  -> compatible multimodal vector candidates -> stable semantic rank
  -> version dispatcher
       v2: frozen direct score blend
       v3: weighted reciprocal-rank fusion
  -> hard-filter validation -> deterministic tie-break -> typed result
```

V3 consumes one-based ranks rather than raw scores. The exact `k`, metadata weight, semantic weight and tie fields live behind `ip-asset-hybrid-v3-rrf`. Before adding a helper, implementation must inspect existing generic/domain RRF utilities; reuse only when their candidate identity and tie semantics match without creating an Agent-to-IP dependency.

## 2. Ranking invariants

- Explicit filters continue to constrain both candidate lanes before fusion.
- Metadata rank remains derived from safe exact fields; semantic rank remains compatible-vector order.
- Missing rank contributes zero. Metadata-only and semantic-only records remain eligible.
- Final ties use metadata rank, semantic rank, creation time and UUID in a frozen direction.
- V2 remains callable by version for evaluator comparison and configuration rollback.

## 3. Offline evaluator

Add `backend/evals/ip_asset_retrieval/` with strict JSONL cases, independent graded relevance, frozen candidate observations, dataset hashing, metrics, stable JSON/Markdown rendering and `--check`/`--write-canonical`. The evaluator imports the production V2/V3 selector. It performs no embedding/provider calls and contains no private filenames, object keys, profile tokens or vectors.

## 4. Anonymous aggregate metrics

Add one table keyed by business date, search version, actual search mode and event kind, with a non-negative count and timestamps. No event row exists.

```text
successful text search -> repository increment(search_results | zero_results)
search-result UI action -> POST safe aggregate event enum
  -> increment(preview|favorite|download_from_search)
summary read -> daily/30d counts + aggregate action ratios
```

The frontend stores only ephemeral last-result version/mode in component state. The telemetry request contains only event enum, search version and mode. Failed favorite/download operations do not send success metrics. Preview intent is counted when the user explicitly opens a search result, independent of browser media caching.

## 5. API and compatibility

- Search response continues to project actual version, mode, degraded reason and items.
- Add one bounded event endpoint and one read-only aggregate endpoint; both reject extra fields.
- The event endpoint is best-effort product telemetry: a telemetry failure never blocks preview/favorite/download, but tests make the failure visible to diagnostics.
- V3 default is config-owned after canonical gates pass; rollback selects V2 without schema rollback.

## 6. Migration and rollback

Create the aggregate table from the implementation-time Alembic head. Upgrade changes no existing rows. Downgrade may drop only aggregate counters and must document that intentional analytics loss; it cannot touch assets, profiles, downloads, favorites or embeddings.

## 7. Privacy and failure semantics

Schema, request models, logs and errors must contain none of the prohibited identifiers in the PRD. Invalid event/version/mode fails with a stable 422/typed domain error. Provider failure still returns metadata results and records the actual degraded mode, not the intended semantic mode.
