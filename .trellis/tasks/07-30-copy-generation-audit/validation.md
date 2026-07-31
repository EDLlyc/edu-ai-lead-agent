# Validation: Evidence-Bound Copy Generation and Audit

Date: 2026-07-30

## Implemented boundary

- Reads only a durable daily Top 1/event-version pair and its validated Tier A/B evidence bindings.
- Persists `no_topic` without brand retrieval, generator calls, or auditor calls.
- Retrieves active parent-targeted brand chunks through the separate brand RAG port.
- Generates one strict draft with typed `external_fact`, `brand_statement`, and `opinion` claims.
- Runs deterministic authority/safety validation before typed brand/risk audit.
- Allows one repair after deterministic or audit rejection; deterministic failure never reaches
  the auditor, and both gates run again on the repaired draft.
- Persists immutable drafts, claims, separate evidence/brand bindings, validation, audit, safe usage,
  repair lineage, job leases, and body-free checkpoints.
- Uses `copy-pipeline-v7`, `moments-generator-v7`, `moments-auditor-v7`, and profile-specific
  `preview-v1` / `moments-rules-v2` policy identities so reviewed provider and rule behavior cannot
  reuse historical run identity.
- Retains only a bounded typed summary of final provider schema failures: up to 12 normalized
  `loc` / `type` pairs. The correction prompt, worker log, PostgreSQL attempt metadata, and API
  projection never receive raw provider content, Pydantic `msg`, `input`, or prompt text.
- Normalizes only one bounded provider JSON object before strict Pydantic validation. It accepts a
  pure object, one `json` code fence, or bounded non-JSON prose around one uniquely balanced object;
  it rejects array roots, multiple/second structures, malformed or unclosed JSON, ambiguous fences,
  non-standard constants, and over-limit envelopes without relaxing any draft/audit field rule.
- Exposes internal enqueue, status, and detail APIs; no publish or social-account API exists.

## Focused automated validation

- `backend/tests/unit/test_copy_generation.py`: 22 passed.
  - valid accepted flow
  - `no_topic` zero-model flow
  - unknown evidence ID and deterministic-before-audit authority
  - exactly one repair and durable exhaustion
  - deterministic failure can consume the same single repair budget before audit
  - restart resumes a persisted valid draft at audit without regenerating it
  - restart uses repository-loaded original brand context instead of issuing a new RAG retrieval
  - LangGraph checkpoint state contains only IDs, stage, attempt, and issue codes
  - minimum evidence-text support and structured coverage for numeric factual assertions
  - complete fake-evidence sentence bounding, strong promotional superlatives, education anxiety,
    personal data, prompt-injection/control-tag echo, unsafe image, and automatic-publishing rules
  - typed provider failure persists/logs only normalized `loc` / `type`; a raw exception cause is
    absent from both paths
- `backend/tests/contract/test_zhipu_copy_provider.py`: 21 passed.
  - one bounded schema correction for generator/auditor
  - generator and auditor requests contain their explicit Pydantic JSON Schemas
  - correction contains only bounded Pydantic validation locations/types, never the invalid raw
    response or input values
  - auditor schema cannot add evidence authority
  - auditor receives bounded evidence and brand bodies needed for brand/risk judgment
  - provider authentication failure projects a body-free typed error
  - final schema failure preserves nested locations, caps the summary at 12, and excludes both the
    initial and terminal invalid input values
  - JSON envelope extraction accepts pure/fenced/explained objects and handles escaped quotes,
    backslashes, and braces inside strings
  - multiple objects, array roots, second structures, unclosed/malformed/ambiguous/over-limit
    envelopes and non-standard constants are rejected with content-free typed diagnostics
  - envelope normalization still leaves extra fields and every claim/binding enum/limit under the
    original strict Pydantic schemas
- `backend/tests/integration/test_copy_generation_repositories.py`: 1 passed with PostgreSQL.
  - enqueue replay returns one run
  - one lease claim only
  - durable `no_topic` with no drafts/model calls
  - status/detail API projection
  - failed workflow attempt persists only safe provider validation metadata while the API exposes
    only the generic `invalid_provider_output` code
- `backend/tests/integration/test_migrations.py`: 1 passed from an empty PostgreSQL database to
  Alembic head `20260730_0008`, including same-run repair lineage, composite evidence provenance,
  and deterministic/audit issue-shape constraints.
- Governance migration and downgrade compatibility: 2 passed against PostgreSQL.
- Strict mypy passed for all new copy-generation modules. Ruff passed for the modified backend and
  focused tests. OpenAPI and frontend generated API types were regenerated.

## Historical real-input fake demonstration

The local development database supplied the real locked daily decision and active brand corpus;
the deterministic fake provider avoided external network/model variability.

- Business date/profile: `2026-07-30` / `preview`
- Selected event ID: `02b8fcf9-5e70-52c5-952c-c5f26005c5fd`
- Selected event version ID: `198f1264-ddae-5bdc-a97b-b14078fab377`
- Active brand versions available: 3
- Successful copy run ID: `3df4a792-e94b-4a6d-bb9d-1d233755a7de`
- Historical result before the final review: `accepted`, repair count 0, one immutable draft,
  258 copy characters
- Claims: one `external_fact`, one `brand_statement`, one `opinion`
- Bindings: one eligible factual evidence binding and one active brand-chunk binding
- PostgreSQL LangGraph checkpoint: present; state contains no copy, evidence, brand, prompt, or
  raw model body

The independent review found that this fake output ended a truncated fact with an incomplete
dependent clause and repeated an `行业首个` promotional superlative. It is therefore retained only
as a workflow/repository demonstration and is no longer treated as copy-quality acceptance. The
fake sentence bounder and deterministic gate now reject this class of output through generalized
`incomplete_sentence` and `unverified_superlative` rules. The upcoming live result must supersede
this historical draft.

The first controlled run exposed missing explicit flush ordering between a persisted audit attempt
and its audit child row. The repository now flushes the parent attempt before inserting the audit,
and the successful rerun above proves the corrected PostgreSQL order.

## Controlled live Zhipu acceptance attempts

The first two attempts used the real locked event version, 13 eligible evidence records, six fixed
active parent-targeted brand chunks, Zhipu `glm-5.2`, one provider attempt, and at most one
structured output correction. Neither attempt printed or persisted a prompt, raw response, API
key, or model input value.

### Attempt 1: missing explicit output schema

- Run ID: `7ab03878-6c2d-497c-98c4-7f825b974eb2`
- Versions: `copy-pipeline-v2`, `moments-generator-v2`, `moments-auditor-v2`
- Provider responses: two HTTP 200 responses for initial generation and its one schema correction
- Terminal result: `failed`, error code `invalid_provider_output`, repair count 0, no draft stored
- Safe validation `loc` / `type`: unavailable; the v2 adapter did not retain a bounded validation
  summary after correction exhaustion
- `safe_metadata`: no provider validation details were written; only the terminal safe error code
  and workflow attempt were persisted

The review identified that the prompts referred to a JSON Schema without including it. Version 3
now includes `MaterialDraft.model_json_schema()` and `AuditVerdict.model_json_schema()` and sends
only safe `loc` / `type` summaries back during the one correction.

### Attempt 2: explicit schema present

- Run ID: `9faafe9d-05ba-4b97-a7ed-fd8b9434bb1c`
- Versions: `copy-pipeline-v3`, `moments-generator-v3`, `moments-auditor-v3`
- Provider responses: two HTTP 200 responses for initial generation and its one schema correction
- Terminal result: `failed`, error code `invalid_provider_output`, repair count 0, no draft stored;
  the audit model was not called
- Safe validation `loc` / `type`: used transiently in the correction prompt but unavailable after
  terminal failure because the adapter deliberately discards model content and the repository
  currently persists only the outer workflow failure
- `safe_metadata`: no validation `loc` / `type`, token usage, or correction count was written for
  this failed provider call; the persisted workflow attempt contains only the safe terminal error

At that point no additional live call was made. The next acceptance pass was required to persist a
bounded, content-free provider diagnostic before obtaining a new explicit live-run approval; the
v4/v5 work below implements and exercises the required `loc` / `type` persistence.

### Attempt 3: v4 production retrieval orchestration probe

- Run ID: `ba63ce25-73ae-4df3-be4b-1e30bb76abd9`
- Versions: `copy-pipeline-v4`, `moments-generator-v4`, `moments-auditor-v4`
- Terminal result: `review_required`, error code `missing_brand_context`, repair count 0
- No generator or auditor provider call occurred. The production brand retriever correctly requires
  query and stored embeddings to share provider/model identity; the active historical corpus was
  embedded under a different provider identity, so this was an acceptance-orchestration error and
  not a structured-output attempt.
- No raw brand text, prompt, provider response, or secret was printed or persisted in diagnostics.

### Attempt 4: v5 fixed active brand context with durable safe diagnostics

- Run ID: `4a90c605-c256-422c-9cac-c9928aa77232`
- Versions: `copy-pipeline-v5`, `moments-generator-v5`, `moments-auditor-v5`
- Input boundary: the same locked Top 1, 13 eligible evidence records, and six database-loaded,
  active, parent-targeted brand chunks valid on `2026-07-30`; no provider-scoped brand retrieval
  was used in this one-off acceptance orchestration.
- Generator: Zhipu `glm-5.2`, one provider attempt per request and one bounded schema correction.
- Terminal result: `failed`, error code `invalid_provider_output`, repair count 0, no draft stored;
  the auditor was not called.
- Persisted and logged final validation summary: `loc=["root"]`, `type="json_invalid"`.
- The correction and terminal failure retained no raw content, `msg`, `input`, prompt, API key, or
  provider response body. No further live run was made.

### Attempt 5: v6 bounded JSON envelope compatibility

- Run ID: `fa40c512-5c7e-49d2-8c8f-31f737914e05`
- Versions: `copy-pipeline-v6`, `moments-generator-v6`, `moments-auditor-v6`
- Input boundary: the same locked Top 1, 13 eligible evidence records, and the same six fixed,
  active, parent-targeted brand chunks used by the v5 acceptance orchestration.
- Compatibility boundary: one pure/fenced/explained, uniquely balanced top-level JSON object may be
  extracted; strict `MaterialDraft` / `AuditVerdict` validation remains unchanged.
- Terminal result: `failed`, error code `invalid_provider_output`, repair count 0, no draft stored;
  the auditor was not called.
- Persisted and logged final validation summary: `loc=["root"]`, `type="json_invalid"`. The model
  response was therefore not a uniquely extractable valid JSON object even with the bounded v6
  compatibility layer.
- No raw content, prompt, response body, API key, `msg`, or `input` was retained or printed. No
  second v6 live run was made.
- A proposed preview policy was not applied to this already-running attempt. It would not change
  this outcome because invalid JSON/schema remains a blocking error under both strict and preview
  policies.

### Attempt 6: v7 non-thinking structured output and preview policy

- Run ID: `aec237c0-1473-4277-a9fc-8eb29112495d`
- Versions: `copy-pipeline-v7`, `moments-generator-v7`, `moments-auditor-v7`, rule `preview-v1`.
- Input boundary: the same locked Top 1, 13 eligible evidence records, and six fixed active
  parent-targeted brand chunks. Requests used `thinking={"type":"disabled"}`, JSON-object response
  format, one provider attempt per request, and at most one structured correction.
- Terminal result: `accepted`; one product repair was used. Draft 1 was deterministically rejected
  for one unbound date and six claim texts not occurring verbatim in the copy. Draft 2 passed the
  deterministic gate and the typed audit returned `accepted=true` with no issues.
- Final output contains three `external_fact` claims, two `brand_statement` claims, and one
  `opinion`. All binding IDs were validated against the supplied evidence/chunk set.
- Manual factual review confirmed all three external claims are directly supported by the bound
  Tier A SenseTime passage: Kairos 3.1 release/model description, 125 ms BF16 inference on NVIDIA
  Jetson Thor, and the three-finger-to-four-finger self-repair example.
- Manual brand review confirmed both brand claims are present in the bound active chunk: nearly ten
  years of focus and the discoverer/inventor/explorer positioning; scientific literacy, innovation,
  curiosity, thinking, creativity, and AI-assisted youth empowerment.
- Safe usage: two successful generation calls and one successful audit call; reasoning tokens were
  zero for all three. No schema-correction request was needed, and no prompt, raw provider response,
  API key, or hidden reasoning was printed or persisted.

## Remaining quality work

- Production quality still depends on richer approved copy examples and future OCR/slide-aware
  brand extraction. These are quality improvements, not blockers for the functional MVP.
- The accepted image prompt references the real logo and Xiaosai IP; the image-generation task must
  use approved assets or a controlled composition step rather than asking a model to recreate them.

## Final identity-drift gate

- `ProviderIdentityMismatchError` is raised before deterministic validation, audit-policy
  transformation, or persistence when a generator/auditor result's provider or model differs from
  the claimed durable bundle.
- Four unit regressions cover generator-provider, generator-model, auditor-provider, and
  auditor-model drift. All pass without persisting a mismatched artifact.
- Final checks from the repository root: backend `pytest` 295 passed; Ruff passed; strict mypy
  passed for 104 files; frontend OpenAPI sync, TypeScript, and ESLint passed; `git diff --check`
  passed. Integration tests required the repository-root invocation so `backend/alembic.ini` was
  loaded correctly.
