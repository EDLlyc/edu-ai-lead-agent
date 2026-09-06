# Independent substantive-policy and release check

Status: **GO for scoped commit/build/preflight; activation remains conditional on every live
gate**. This report covers the
selection-only `.12` candidate and its task-local offline release transaction. It does not claim
that `.12` is deployed. Production recovery AC2/AC3 was independently proven on the still-running
`.11` release by the September 6 morning formal deliveries; that recovery evidence is separate
from this candidate review.

## Findings fixed

1. `backend/app/domain/editorial_relevance.py` allowed relationship-only current-affairs phrases
   such as “会议明确人工智能合作方向” to authenticate an AI subject. Weak relationship verbs are
   now continuation-only, publication of a cooperation/initiative statement is insufficient by
   itself, and genuine research-result predicates such as “表明/证实/证明” remain supported. New
   positive and negative regressions cover the boundary.
2. The new v4 identity had been added to the acquisition-supported rule set. A future bad source
   configuration could therefore have run a body-dependent selection rule during title-only
   acquisition. Acquisition remains restricted to literal v2/v3; the evaluator separately accepts
   v4 for selection. Tests pin all eleven source seeds to v3 and forbid v4 in the acquisition set.
3. The existing whole-file topic repository test shared one fixed semantic vector across unrelated
   stories. Exact deployed-source 5c reproduces the resulting rerank test failure when the file is
   run as a suite, while the test passes alone. Candidate fixtures now derive deterministic distinct
   vectors from candidate IDs; the complete repository file passes without changing runtime
   duplicate/event behavior.
4. The release validator's reviewed September 6 06:00 CST cutoff had expired. The one-shot bytes
   are now pinned to the next safely reviewable September 6 17:00 CST preparation boundary. Runtime
   derivation rejects them before the noon window closes, inside any active window, after the 16:45
   margin, after a business-date change, or when the Monday 09:00 weekly producer would be earlier.
   The handoff and regression fixture use the same exact cutoff.
5. Generated release-test bytecode was removed from the task release directory so it cannot be
   mistaken for a task-prefix audit artifact.

## Verification completed

- Substantive/editorial/topic/service/scheduler focused unit files: 260 parameterized tests passed.
- New substantive unit file alone: 65 parameterized tests passed.
- Whole topic repository on isolated PostgreSQL/pgvector: 12/12 passed. Exact 5c baseline reproduces
  the former suite-order rerank fixture failure; the same test passes alone.
- Relevant copy/WeCom unit regression: 130 passed; isolated PostgreSQL copy/delivery integration:
  8/8 passed.
- Historical replay under network isolation: six `.6`-`.11` configs, 1,080 score/explanation
  combinations, 12 literal v2/v3 editorial projections, and 11 source identities match exact 5c;
  both sides have SHA-256
  `a9f785d62edb60860ae14a483ad79c432be82a8a04bf51313841d611b34ff56d`.
- Task-local release regressions: 134/134 passed with no Docker daemon, provider, production or
  network call. General release contract tests: 68/68 passed.
- Ruff lint across `backend/app` and `backend/tests`: passed. Ruff format on all nine touched Python
  files: passed. Provider-free Compose render, shell syntax and scoped diff checks: passed.
- Strict project mypy: candidate and exact 5c both report the same two untouched
  `backend/app/local_exact_target_selection.py` Literal errors; no candidate-only type error.
- Final post-fix provider-free full unit comparison: candidate has 30 failures versus exact 5c's
  31. The candidate failure-ID set is an exact subset of the baseline set, with zero new failures;
  the removed failure is the intentionally updated current-default assertion.
- The checked 12-file product patch was whitespace-normalized for commit after review; its committed
  SHA-256 is `6e4ac45cd12d5b33ede3699794b0f64147ebbd01a7b7cd41d61eb967e4d48de8`, and
  `git apply --check` succeeds against exact deployed source 5c. This normalization does not change
  any applied source hunk.

## Remaining external/operational gates

- The full unit suite is not globally green because the exact 5c baseline already lacks ignored
  private visual/demo fixtures and has unrelated content-slot/IP/rerank fixture drift. These are
  not `.12` defects and are not silently bundled into this release.
- Main must commit the exact reviewed bytes, rebuild from the fetched clean release ref, capture a
  fresh production baseline, run the sealed preflight after 13:30 CST, and finish activation before
  16:45 CST. Any current-state, source/image/config, counter, frozen-job, cutoff, weekly-schedule,
  lock, backup or zero-new-`.12` drift remains a hard stop.
- No SSH, model/provider request, production write, send, commit, push, image build or deployment was
  performed by this checker.
