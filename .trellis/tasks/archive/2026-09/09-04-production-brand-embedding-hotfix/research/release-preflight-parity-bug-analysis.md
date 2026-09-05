## Bug Analysis: source mode compatibility ran only during activation

### 1. Root Cause Category

- **Category**: D/E — Test Coverage Gap and Implicit Assumption
- **Specific Cause**: the stage already contained both the captured production source manifest and
  the candidate source manifest, but their path type and executable-class compatibility was checked
  only while preparing extracted source during activation. `--preflight-only` therefore passed,
  then the real run created its one-shot attempt marker before discovering that
  `deploy/release/deploy.py` and `deploy/release/release_tool.py` were `0600` in production but
  `0755` in Git.

Bayesian diagnosis started with three hypotheses: production/candidate mode drift (50%), archive
mode normalization error (30%), and path/type drift (20%). The captured baseline plus candidate
manifest showed exactly two executable-class mismatches; both old and candidate Git trees used
`100755`, production used root-owned `0600`, and every repository invocation uses `python` or
`python3`. That evidence updates the first hypothesis to high confidence (about 95%); archive and
path/type corruption are contradicted by the exact manifest comparison.

### 2. Why Fixes Failed

1. **Compose preflight fix**: it correctly repaired the immediately observed topology failure, but
   did not enumerate every later activation-only assertion.
2. **Preflight success**: image, source hashes, Compose topology, and one-shot availability passed,
   but destination compatibility remained hidden inside `prepare_candidate_source` after the
   attempt marker. This was an incomplete phase-parity contract, not an intermittent production
   failure.

### 3. Prevention Mechanisms

| Priority | Mechanism | Specific Action | Status |
|---|---|---|---|
| P0 | Architecture | Validate baseline/candidate path type and executable class in the pure stage validator. | DONE |
| P0 | Runtime | Repeat compatibility in operator preflight and under the release lock before consuming the attempt identity. | DONE |
| P0 | Source contract | Store the two interpreter-invoked Python tools as non-executable `100644`. | DONE |
| P0 | Test coverage | Reject missing paths, type drift, executable drift, and any ordering after image load/attempt/quiesce. | DONE |
| P1 | Documentation | Record phase-parity requirements in backend release quality guidance. | DONE |

### 4. Systematic Expansion

- **Similar Issues**: any assertion that depends only on checksum-bound stage files and a captured
  baseline can be accidentally left in the mutation path.
- **Design Improvement**: pure validation is the authoritative compatibility layer; operator checks
  are TOCTOU repetitions, not the first place a deterministic mismatch is discovered.
- **Process Improvement**: release tests must compare preflight gates with deterministic activation
  preconditions and prove they precede image load, attempt markers, and quiescence.

### 5. Knowledge Capture

- [x] Updated `.trellis/spec/backend/quality-guidelines.md`.
- [x] Added executable regression coverage in the task-local release harness.
- [x] Added this production failure record to the active task.
- [x] Confirmed no project `src/templates/markdown/spec/` tree exists to synchronize.
