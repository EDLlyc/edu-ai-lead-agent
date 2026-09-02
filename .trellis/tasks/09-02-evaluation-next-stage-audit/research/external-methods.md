# External evaluation methods and project fit — 2026-09-02

Only primary/official sources were used. These are method references, not dependencies that must be
installed.

## Evaluation validity and human calibration

- OpenAI's 2026 evaluation playbook argues that the harness and validity checks are part of the
  result, and calls out contamination, reward hacking, broken problems, refusals and budget/tool
  choices as threats to validity:
  https://openai.com/index/trustworthy-third-party-evaluations-foundations/
- GDPval uses detailed occupational rubrics and blinded expert comparison; its automated grader is
  treated as an estimate rather than a replacement for experts:
  https://openai.com/index/gdpval/

**Project fit:** add a validity section to live reports and do not replace deterministic hard gates.
The user deferred people-based calibration, so Codex output stays Seed even after multiple review
passes; the cited expert-grading practice remains a known future gap rather than a claim of current
coverage.

## Retrieval qrels and pooling

- NIST TREC describes relevance judgments as the core of a reusable test collection and uses pooled
  top results from multiple runs when complete corpus labeling is too expensive:
  https://trec.nist.gov/data/reljudge_eng.html
- TREC's recent overview documents graded relevance, assessor subjectivity and the assumptions and
  bias boundaries of pooling:
  https://trec.nist.gov/pubs/trec33/papers/overview_33.pdf

**Project fit:** because this corpus has only 41 images, complete labeling is preferable. Pooling is
an acceptable fallback only if time is constrained and its incomplete-judgment assumptions are
reported. Keep query/corpus/qrels fingerprints coupled.

## RAG and long-form content

- RAGAS separates retrieval quality, context use/faithfulness and answer quality:
  https://arxiv.org/abs/2309.15217
- RAGChecker adds claim-level diagnostic metrics for retrieval and generation and reports stronger
  human correlation than simpler aggregate metrics:
  https://arxiv.org/abs/2408.08067

**Project fit:** reuse the project's typed article claims and evidence IDs to measure unsupported,
contradicted and uncovered claims. Do not adopt a generic framework that discards the existing
claim/evidence contract. The official-account Reviewer task remains the owning implementation.

## Agent evaluation

- Tau-bench evaluates tool agents against final database goal state and uses repeated-trial
  `pass^k` to expose inconsistency:
  https://arxiv.org/abs/2406.12045

**Project fit:** once the governed Reviewer path is stable, add final-state correctness, trajectory
policy checks and repeated trials under fixed budgets. Current 42/42 deterministic Workbench results
must remain labeled contract conformance.

## Image generation

- TIFA decomposes prompts into visual questions and measures interpretable text-image faithfulness,
  especially objects, counts, attributes and spatial relations:
  https://arxiv.org/abs/2303.11897
- HPS v2 is trained on large-scale human pairwise preferences and demonstrates why generic CLIP/FID
  scores do not fully represent human preference:
  https://arxiv.org/abs/2306.09341

**Project fit:** use TIFA-style atomic prompt constraints for semantic/compositional failures and
pairwise human preference for aesthetics. Neither method directly validates the proprietary
赛先生/小赛 identity, so approved-reference identity needs its own human-calibrated rubric and must
not be inferred from a generic aesthetic score.

## Methods intentionally not adopted now

- No new SaaS eval platform: the repository already has strict JSONL, canonical reports, CI and run
  identities. A platform migration would not create human truth or fix abstention.
- No single composite quality score: hard factual, identity, privacy and crop failures cannot be
  offset by style/aesthetic points.
- No LLM-only Gold generation: it accelerates case authoring but does not establish human alignment.
- No production A/B before sufficient traffic: anonymous daily aggregates are useful trends but do
  not currently provide randomized, unique-search causal evidence.
