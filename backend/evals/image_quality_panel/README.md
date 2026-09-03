# GLM-5V-Turbo image-quality calibration

This package evaluates exactly one image-recognition model: direct Zhipu `glm-5v-turbo`. It does
not call ToAPIs or any Claude, Gemini, GPT, or other GLM identity. It has no human or external
labels for subjective cases and must never be described as Human Gold, consensus, inter-model
agreement, or human agreement evidence.

The frozen source catalog contains six independent public portfolio PNG families. Four checked JPEG
publication derivatives remain attached to their parent family and do not increase the effective
sample count. `preflight_sources` checks the external-evaluation authorization basis, public-only
paths, tracked clean Git blobs, content hashes, media types, and dimensions before any derivative is
built.

The deterministic dataset has 48 derived pairs: eight per quality dimension, 36 objective recipe
anchors plus 12 unlabeled subjective cases, and a family-disjoint 24 calibration / 24 untouched
holdout split. Reports always state both `case_n=48` and `effective_source_cluster_n=6`.

GLM-5V-Turbo receives all 48 cases in AB and BA order plus an AB/BA repeat of all 12 subjective
cases: `48*2 + 12*2 = 120` calls. The first planned call is the four-image batch-diversity case.
Identity, capability, schema, usage, or cost failure on that call stops the plan; there is no
fallback or retry. Every presented image reference is separately HMAC-blinded for its attempt.
The direct visual request uses the frozen `zhipu-vision-v1` dialect: it omits the text-only
`response_format`, disables thinking and sampling, and permits no caller-supplied provider options.
Its response boundary accepts only exact JSON after trimming outer whitespace, or one standalone
lowercase `json` Markdown fence containing that exact object. Prose, multiple objects/fences,
duplicate keys, unknown fields, invalid arm invariants, and request-disallowed issue codes fail
closed. Safe evidence distinguishes framing, schema/invariant, and allowlist/policy failures without
retaining raw provider content or prompts. The default Reviewer JSON profile is not normalized.

Run the provider-free validation with:

```bash
cd backend
python -m evals.image_quality_panel.runner preflight
```

The provider-free `live` boundary validates private hash-bound manifest and authorization files,
then fails closed. The application entrypoint constructs the one direct Zhipu one-shot transport
and reads only `AI_PLATFORM_API_KEY`, after all evidence and output-directory checks pass.

Objective cases report pair accuracy, arm decision macro-F1, critical false-accept rate (FAR),
acceptable false-reject rate (FRR), critical-flag false-positive/negative rates, confusion counts,
and bad-case aliases. Unlabeled subjective cases report only the model's AB/BA position stability,
repeat stability, coverage, and abstention. Reports also include calibration/holdout source-cluster
counts, latency, known/unknown usage, and native CNY cost. They explicitly set
`single_model_only=true` and `external_label_n=0`; no aggregate quality score or activating model
recommendation is emitted.
