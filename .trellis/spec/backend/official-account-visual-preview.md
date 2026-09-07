# Isolated Official-Account Visual Preview

## 1. Scope / trigger

Use this additive operator to demonstrate fresh paragraph-bound illustrations for the frozen
September 7 application-case Article. It is not a worker, replacement draft, durable V2 release,
general arbitrary-article API, or production activation. Existing Article/source bytes, database
rows, scheduled jobs, environment files and social drafts remain unchanged.

The source-run allowlist is explicit in `SOURCE_RUN_ID`. Broadening it requires reviewed input
contracts, not changing a UUID on an already billed preview. Production deployment is a separate
gate after the user accepts the visible sample.

## 2. Signatures

```bash
PYTHONPATH=backend python -m app.official_account_visual_preview_main \
  --source-dir <private-capture> --source-manifest-sha256 <exact-sha>
# Default: preflight only, no provider/settings/database client construction.
# Add --live --output-dir <fresh-private-directory> for the authorized sample.
# --rerender --preview-dir <completed> --preview-manifest-sha256 <sha> \
#   --output-dir <fresh> is provider-free.
# --finalize --preview-dir <completed> --preview-manifest-sha256 <sha> \
#   --browser-report <exact-report> is provider-free.
```

`ImageGenerationRequest.output_size: Literal["1024x1024", "1536x1024"] = "1024x1024"`
adds explicit per-request native geometry. Existing square callers are unchanged.

`Settings.image_quality_audit_model` / `IMAGE_QUALITY_AUDIT_MODEL` defaults to
`glm-5v-turbo`; it does not inherit the text-generation model.

## 3. Contracts

- Input `official-account-visual-preview-input-v1` pins an external manifest SHA and an exact
  bounded member list. Article, source, article/render identities, block fingerprints, media
  checksums, approvals and source context lineage must agree before credentials or dispatch.
  Duplicate JSON keys, symlinks in any path component, traversal and excess bytes are rejected.
- Use approved complete reference publications, minimum 512-pixel short edge; exclude tiny avatar
  references. Record actual `deterministic_tag` selection and zero embedding calls. Never claim a
  Qwen/multimodal embedding selector ran when it did not.
- Each of five distinct exact source blocks produces one reference-conditioned Comfly
  `gpt-image-2` request at native 1536x1024. The preview request fingerprint binds the production
  base plan fingerprint, fresh preview identity, explicit size and exact prompt SHA. Preserve
  the base plan identity separately; do not mislabel this as a persisted production plan.
- Comfly validates declared and decoded dimensions for direct raster, synchronous Base64/URL,
  and asynchronous task Base64/URL response paths. Do not stretch an accepted square response
  into a claimed native landscape. Unsupported fake/ToApis landscape requests fail before calls.
- Final body assets are metadata-free 1536x1024 JPEGs, distinct from each other and old catalog
  assets; perceptual checks also flag near-duplicates. Exact original news-image bytes and
  source/credit/unverified-rights/context-only labels are preserved. Generated art is not news
  evidence. A separately recorded 2.35:1 cover crop derives from a new scene, not an old cover.
- The only preview judge is direct Zhipu `glm-5v-turbo` at
  `https://open.bigmodel.cn/api/paas/v4`. Audit the five final JPEGs and final cropped cover, with
  approved references and bounded criteria. Require exact returned model/request identity.
  Use disabled thinking and deterministic sampling; do not send unsupported response-format
  options to this audit profile. OCR retains its separate JSON-object request profile.
- Parse both HTTP completion envelope and audit content with duplicate-key/nonfinite rejection.
  Permit one exact JSON fence only for the Zhipu audit content. Extra prose, competing objects,
  unknown issue codes or missing/mismatched identity cannot pass.
- Preview acceptance is separate from production `observe`. All six audits must be available,
  accepted and issue-free; warnings also require review. The existing port returns accepted/issues,
  not numeric scores or human labels. Production quality-evaluation flags remain unchanged.
- Reserve a fresh private directory with exclusive files. Persist/fsync application intent before
  each request and physical transport intent before dispatch. Initial envelope: five generation
  POSTs, six audit POSTs, one attempt each. Polls and one allowed download are separately bounded.
  Unknown dispatch/response outcomes are retained and never automatically replayed.
- Keep successful siblings, raw image artifacts and complete intent/result ledgers after failures.
  Hash-bind evidence to the manifest. Completed replay/finalize rejects changed, missing or
  unlisted paid/raw/transport evidence; rerender preserves paid bytes and cannot call providers.
- Use the pure V2 body renderer with typed media, not fabricated durable rows or human approval.
  Keep `local_only=true`, `published=false`, `database_persisted=false`,
  `production_activated=false`, `drafts_replaced=false`, `human_approved=false`.
  Do not write to watched inboxes or construct DB/queue/WeChat/WeCom clients.
- Browser evidence binds exact content/body/preview/media hashes, ordered widths 320/430,
  seven loaded images, zero failures/overflow/external requests and exact copy-root/body equality.
  Only a matching actual report can append acceptance; initial output remains `not_run`.
  Source JSON is private; public operational summaries contain no credentials, provider prose,
  private object URLs/IDs, prompts or task IDs.

## 4. Validation and error matrix

| Condition | Required result |
|---|---|
| Input/approval/checksum/identity/path invalid | Fail before credentials and all calls |
| Output exists or is watched | Refuse without replay or overwrite |
| Wrong model/endpoint/credential configuration | Fail closed before provider dispatch |
| Wrong raw native dimensions, even if metadata claims the requested size | Reject; do not hide via resize |
| Transport timeout, parse failure or outcome unknown | Preserve evidence, no automatic paid retry |
| Judge unavailable, rejected, warning, identity mismatch | Quality false, never substitute another judge |
| Valid rendered sample but browser not run | Preview not accepted |
| Browser report has wrong hashes, widths or observations | Refuse finalization |
| Complete accepted preview | Still unpublished and not production-activated |

## 5. Good / base / bad cases

Good: five real landscape generations, six final-byte GLM audits, unchanged source photo and
Article, exact passing mobile report, followed by human sample review.

Base: default CLI preflight and completed rerender/finalize use zero provider calls.

Bad: enlarge a tiny catalog avatar, audit raw rather than cropped bytes, reuse old images as
fresh generation, treat a schema-valid model warning as acceptance, or push a preview to drafts.

## 6. Tests required

Cover strict source validation and every path/hash/identity boundary; distinct block planning;
small-reference exclusion; all native-size adapter response branches; final-byte body/cover
audits; exact Zhipu request and response model; strict inner/outer JSON parsing; single physical
POST budgets; intent-before-dispatch; preserved paid siblings; no restart/retry; replay evidence
completeness; and hash-bound zero-call rerender/finalize. Real-adapter MockTransport integration
must observe exactly five generation and six audit POSTs without network or database effects.
Keep square generation, OCR, production observe and existing renderer regressions unchanged.
Live/model/browser acceptance is separate evidence; offline tests alone never prove live quality.

## 7. Wrong vs correct

Wrong: set the production generated-visual flag, reuse old ready rows, and describe the result as
a newly generated and human-approved release.

Correct: freeze and verify read-only source bytes, run a new bounded local-preview identity,
audit final pixels, validate exact mobile output, and request sample acceptance before a
separately reviewed production activation.
