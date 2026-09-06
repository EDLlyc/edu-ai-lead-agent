# Substantive topic implementation checkpoint

Worktree: `.trellis/worktrees/substantive-news-scope`, base `5c560da71bcbb61b765d3fe82c742cf2d5e676e1`.

Initial eight-runtime-path implementation restored. Selection .12 opts into v4; acquisition v3
alias remains frozen. V4 authenticates bounded topic/action clauses and immediate technical-detail
continuations, with deduplicated primary-content coverage. .12 alone removes synthetic taxonomy
labels from subject authentication. Historical config dispatch remains explicitly versioned.

## Implementation handoff

- Final runtime allowlist: `.env.example`, `backend/app/domain/editorial_relevance.py`,
  `backend/app/domain/topic_selection.py`, `backend/app/application/services/topic_selection.py`,
  `backend/app/core/config.py`, `backend/app/infrastructure/db/topic_selection.py`, `compose.yaml`,
  `scripts/doctor.sh`.
- Test allowlist: new `backend/tests/unit/test_substantive_topic_scope.py`,
  `backend/tests/unit/test_topic_selection.py`, `backend/tests/unit/test_topic_selection_delivery.py`,
  `backend/tests/integration/test_topic_selection_repositories.py`.
- Historical tests pin .11 where their original intent requires it. The service default assertion
  now matches .12/v4 and the unchanged qualified-authoritative priority v1.
- V4 bounds raw input before normalization, requires local independent topic plus concrete action
  or explicit measured-result predicate, de-duplicates clauses, and admits at most two immediate
  technical-detail continuations before a new anchor. A paragraph or nontechnical subject resets
  that allowance. At least 12 substantive characters and half of considered unique content are
  required. Body insufficiency never becomes title-only admission.
- Relationship-only publication/clarification/support/proposal language cannot authenticate a
  technical subject. Those weak verbs may only continue an already established subject; dedicated
  research findings, measurements, governance standards and product engineering remain eligible.
- Compound nouns such as quantum computing or recoverable rockets cannot supply their own action.
  Real semiconductor reports may qualify without synthetic AI taxonomy, with a conservative 0.50
  general-frontier value. This is a deterministic policy, not measured human precision/recall.
- .12 joins content-bearing summary/facts as sentences (not artificial paragraphs) for subject
  continuity. Historical projections and orthogonal taxonomy/product-fit inputs stay unchanged.
- Acquisition's supported-rule set remains literal v2/v3. V4 is supported only at the evaluator's
  explicitly run-pinned selection boundary, so title-only source discovery cannot opt into it.

## Verification performed

- Final focused unit suite: 260 passed across substantive scope, editorial relevance, topic
  selection, topic service and content scheduler. The substantive file alone has 65 passing
  parameterized cases after independent relationship/research/acquisition-boundary additions.
- Six new real isolated PostgreSQL tests passed: category/incidental non-rescue; neutral-title
  summary/measurement/pronoun projection; science education and AI policy; expired .11 snapshot
  conflict; fresh .12 snapshot/replay. Initial failures exposed fixture analysis-ID loss and
  identical fake vectors merging unrelated stories; both fixtures corrected without runtime veto
  bypass. Every accepted projection retains its actual evidence binding.
- Whole topic repository file: 12/12 passed. Exact 5c reproduces the older rerank atomicity failure
  when the whole file shares one constant fake vector, while the same test passes alone. Test-only
  candidate-derived vectors now isolate unrelated stories without changing runtime event logic.
- Relevant copy/WeCom unit regressions passed 130/130 and isolated PostgreSQL copy/delivery tests
  passed 8/8. General release contract tests passed 68/68.
- Full app/tests Ruff lint passed; all nine touched Python files pass Ruff format. The untouched
  `test_title_relevance_ingestion.py` has existing full-tree format drift; do not silently bundle it.
- The exact project strict-mypy command reports two untouched Literal errors in
  `local_exact_target_selection.py`; exact 5c reproduces both and no candidate-only error exists.
- Shell syntax, provider-free Compose rendering, and `git diff --check` passed.
- Own frozen historical digest verifies 1,080 scoring/explanation combinations, literal v2/v3
  results, and all 11 acquisition fingerprints against exact deployed source. Independent reviewer
  has separately reproduced snapshot/fingerprint/replay parity.
- The final disconnected full-unit candidate run has 30 failures versus exact 5c's 31. Its failure
  IDs are an exact subset; the one removed baseline failure is the intentionally updated .12
  current-default assertion. Missing ignored private/demo fixtures and unrelated old drift remain
  visible rather than being bundled into this change.

Recovery patch includes all 12 product/test files, including the new untracked test and checker
self-fixes. Main-owned spec changes remain excluded from this product patch. The independent
checker issued a scoped GO in `substantive-independent-check.md`. No model, SSH, production
mutation, commit or push was performed by the implementation/check agents. Production delivery
recovery was separately proven by the still-deployed `.11` morning run; this `.12` candidate has
not yet been activated.
