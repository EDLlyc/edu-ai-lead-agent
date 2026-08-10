# Implementation Plan

1. Update copy policy and version identifiers.
   - Define the recoverable copy-quality allowlist separately from hard safety/integrity codes.
   - Normalize allowlisted audit findings to warning in the active policy.
   - Include allowlisted quality findings in the single repair payload where appropriate.
   - Bump copy rule/prompt versions and update prompt language to describe warning-only quality findings.

2. Extend image recovery.
   - Route a second ordinary quality/OCR/audit failure through the existing brand-catalog fallback.
   - After terminal transient provider retries, attempt the same fallback when reserved references are valid.
   - Keep provider rejection at one neutralized retry and preserve hard output/security failures.
   - Preserve leases, fingerprints, counters, snapshots, safe provenance, and package status transitions.

3. Upgrade the private visual catalog and reference selection.
   - Add bounded JSON metadata for asset kind, display name, variant group, and selection tags.
   - Separate clean identity references from action/scene references and make style references optional.
   - Add stable per-run variant selection while keeping persisted references authoritative for retries.
   - Ensure Comfly receives the selected ordered multi-reference array and ToAPIs retains its single-reference fallback.
   - Add a one-shot Zhipu vision annotation command for actual PNGs; validate constrained responses and fall back per asset to filename/directory labels without blocking manifest generation.

4. Update specifications and structured logging assertions.
   - Align `agent-pipeline.md`, `error-handling.md`, and any image/copy contract text with the new transitions.
   - Verify logs contain bounded IDs/codes and no raw content or secrets.

5. Add focused regressions.
   - Copy warning-only acceptance, hard finding rejection, one repair, and transient retry.
   - Image second-quality-failure fallback, exhausted-transient-failure fallback, provider rejection fallback, and no-reference terminal state.
   - Assert no third provider call and no duplicate successful artifact.
   - Visual annotation response parsing, allowlist filtering, model failure fallback, and no raw provider-content persistence.

6. Run quality gates.
   - `conda run --name edu-ai pytest` on affected unit/contract tests.
   - `make backend-format-check backend-lint backend-typecheck`.
   - `git diff --check` and inspect the final diff for unrelated changes.
