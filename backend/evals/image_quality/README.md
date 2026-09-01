# Image-quality policy evaluation

This suite is a provider-free regression harness for the shared image-quality schema,
six-dimension taxonomy, metric aggregation, and decision policy. It uses 48 sanitized,
hand-authored cases plus frozen observations. It makes no network request and contains no image
bytes, private path, raw prompt, provider response, embedding, or internal object key.

The six independently reported constructs are:

1. semantic faithfulness;
2. approved IP identity;
3. OCR and exact visible text;
4. aesthetics and rendering artifacts;
5. final-publication crop and layout;
6. batch diversity.

Critical issues reject a fixture, warnings require manual review, and unavailable observations stay
explicitly unavailable. The report intentionally has no aggregate image-quality score: a high
aesthetic signal cannot offset a wrong character, missing topic entity, incorrect text, destructive
crop, or exact duplicate.

## Evidence boundary

The checked report proves only that strict loading, frozen-observation aggregation, hard-gate
policy, diagnostics, and canonical drift replay deterministically. The fixture labels and
observations were authored for contract coverage. They are **not** a live-model benchmark,
multi-annotator gold set, judge-human agreement measurement, calibrated threshold, or production
quality/effectiveness claim.

The reported 100% fixture agreement and zero false-pass rate therefore must not be presented as
model accuracy. Human calibration and opt-in live evaluators remain separate future tracks.

## Files

- `rubric.v1.json` owns the versioned construct and closed issue taxonomy.
- `cases.v1.jsonl` owns evaluator-only labels and per-case atomic criteria.
- `observations/frozen.v1.jsonl` owns provider-free observations bound to synthetic publication
  SHA-256 values.
- `canonical-report.json` and `canonical-report.md` are reviewed deterministic artifacts.

The shared provider-independent API is `app.domain.image_quality_eval`. Production adapters can use
`build_image_eval_issue`, `build_image_eval_observation`, and `decide_image_eval` without importing
this eval package or SQLAlchemy. Unknown provider issue codes map to the stable
`provider_audit_unclassified` warning in `aesthetics_artifacts`, which requires manual review rather
than accepting an arbitrary dimension.

## Commands

From the repository root:

```bash
make image-quality-eval
```

To inspect a report without comparing checked artifacts:

```bash
cd backend && python -m evals.image_quality.runner
```

Only after an intentional, reviewed dataset/rubric/policy change:

```bash
cd backend && python -m evals.image_quality.runner --write-canonical
```

Ordinary checks must use `--check`. The runner prints bounded `expected=...:actual=...` paths for
JSON drift and does not silently promote a changed baseline.

## Optional production observation

`IMAGE_QUALITY_EVAL_MODE=off|observe` is independent of the existing material-package audit flag
and defaults to `off`. In `observe`, the official-account worker audits the final 1536×1024 JPEG,
not the raw provider image, and atomically stores a hash/version-bound record with the visual's
`ready` transition. Missing or failed evaluator capability is recorded as `unavailable`; accepted,
review, rejected, and unavailable observations do not change the current release gate. Historical
ready images without a record remain deliverable and are described only as locally inspected.
