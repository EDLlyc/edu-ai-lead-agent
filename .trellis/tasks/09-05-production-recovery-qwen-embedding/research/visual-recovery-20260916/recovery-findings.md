# Recovery findings retained from the interrupted research

- Ordinary run retry refuses result_unknown. Same material/identity enqueue returns
  the old run by request fingerprint. The single producer does not claim unknowns.
- Naive cloned run sharing article/render violates run-bound composite FKs;
  independently cloning those rows collides with globally unique generator/render
  fingerprints. Do not fabricate a prompt/model version or content change to bypass.
- ImageGenerationRequest already supports provider_request_fingerprint; Comfly
  uses it for Idempotency-Key while preserving the logical result fingerprint.
- Therefore use an explicit authorized logical-slot compensation with immutable
  workflow attempt history and protected pre-change snapshots. Only the active
  slot projection/run/edition can advance under the reviewed exact-target operator.
- Old unknown attempts and any accepted article/render/audit/body remain unchanged;
  current visual projection updates are never represented as proof the original
  paid request failed. No recoverable provider task ID is present in persisted
  records for the original image, and its original failure subtype was lost.
- API/current supplier GET /v1/models returned HTTP200 and listed the configured
  image model; this verifies current auth/catalog availability only, not generation.
- Today's exact IDs and original statuses are in prd.md. Use safe hashes/counts
  for research output; full snapshots stay in a protected operator receipt, never
  committed to this repository. Keep provider/body/secret values out of diagnostics.

Worker ownership: error-classification implementer owns existing executor/DB
claim files; compensation implementer owns the new DB module, claim DTO,
operator and new tests; release implementer owns release-* scripts and tests.
