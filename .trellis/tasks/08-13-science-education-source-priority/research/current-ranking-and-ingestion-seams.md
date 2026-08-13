# Current ranking and ingestion seams

## Scope

This note records code-backed constraints for extending acquisition and topic ranking toward science education, AI education, and the supplied product matrix. It is planning evidence, not an implementation decision.

## Current acquisition behavior

- The controlled registry is `backend/app/infrastructure/ingestion/source_profiles.py` and currently contains nine source seeds.
- Eight general profiles use `ai-title-v1`. `execute_acquisition.py` evaluates this rule before detail fetch and therefore filters out science-education stories whose titles do not also contain a recognized AI term.
- The Ministry profile alone uses `moe-science-v1`. It prioritizes title matches, fills a bounded detail-probe window with title misses, and then evaluates title plus at most 6,000 normalized content characters.
- Relevance dispatch in `execute_acquisition.py` is currently an explicit branch on the installed rule-version string. Adding more rule families by copying source-specific branches would create another special-case chain; a shared bilingual science/AI-education policy needs one owned domain interface and typed audit projection.
- Every profile already carries language, timezone, connector/parser versions, relevance rule version, host/path allowlists, rate limit, robots status, and optional HTTP fallback. Source and source-version fingerprints make profile changes immutable and replayable.
- The generic HTML connector supports per-source discovery selectors, URL filters, bounded discovery, detail selectors, URL/date parsing, and trafilatura fallback. New sources still require fixed fixtures because live HTML is not an authoritative test oracle.

## Current topic projection and ranking behavior

- `TopicCandidate.ai_relevance` is currently projected as `1.0` whenever an event has any factual category, not only when it is AI-related. It cannot serve as the new science/AI-education feature without a versioned correction.
- `parent_relevance` is derived from the event's seven-category factual taxonomy. It is a broad editorial/audience proxy, not a mapping to the product matrix.
- `science-policy-priority-v2` is evaluated only after vetoes and threshold checks and only for an occurrence carrying `moe-science-top1-v1`. It requires a science/technology/AI/robotics education topic plus a policy/action term, and then places the candidate in a sort group before all ordinary eligible candidates.
- The current source-priority metadata is propagated from source version -> article occurrence -> event projection -> `TopicCandidate` -> persisted score explanation. Historical scoring snapshots must retain that behavior.
- A new scoring version can replace the source-specific absolute priority for new runs while leaving historical snapshots readable. Hard vetoes, threshold, `no_topic`, freshness, repetition, source trust, deterministic tie-breaks, and daily locks are separate contracts and must remain intact.
- Score explanations persist raw features, normalized features, weights, positive/penalty components, total, priority rule/reason, and rank. New relevance/product signals must survive the same config-snapshot and API round trip.

## Product-matrix taxonomy extracted from the supplied page

The product page positions the brand around “科学第四主科 · AI 第五主科” and contains the following stable matching directions:

1. Science literacy and inquiry for ages 4–12, including primary science and transition toward physics/chemistry.
2. Mathematics, physics, chemistry, and biology subject transition for ages 11+.
3. AI literacy and project-based learning for ages 7–15.
4. Embodied robotics, AI Agent engineering, RAG/LLM application, AI safety, AI × mathematics, 3D printing, hackathons, and entrepreneurship.
5. Science/technology competitions, innovation projects, and talent-development pathways.
6. University, laboratory, technology-company, major-science-facility, study-tour, and camp experiences.

Product content is brand context. A matched direction may explain editorial fit but must never become factual evidence for an external-news claim.

## Language boundary

- Acquisition candidates, normalized articles, governance jobs, and evidence APIs already persist a bounded language string; no factual-candidate database constraint limits these layers to `zh-CN`.
- The `zh-CN` hard restriction found in the codebase belongs to private brand-knowledge documents, not external evidence.
- Governance analysis receives the candidate language. Before enabling English sources, fixture/provider tests must prove the existing model prompt/schema can analyze English evidence and still preserve exact quote/offset bindings.
- The downstream copy product remains Chinese. Acceptance therefore needs an English-evidence-to-Chinese-copy case with original URL, original quote, language metadata, and Chinese factual wording all auditable.

## Recommended implementation boundary (pending user product decision)

- Use science/AI-education relevance as the acquisition eligibility boundary for broad sources.
- Compute a versioned, bilingual, event-level `science_education_relevance` feature from stored governed title/summary/category projections; do not infer it from source identity alone.
- Compute a separate `product_alignment` feature with named matched directions and capped contributions. Treat it as editorial fit, never evidence.
- Make science-education relevance and product alignment the dominant positive share of a new immutable preview scoring config, while retaining source trust/diversity, freshness, and communication potential.
- Prefer soft product alignment rather than a product hard filter so important science-education policy and emerging topics remain visible even when they do not match today's catalog. This is the one product-owned decision still to confirm.
- Retain the historical Ministry priority policy only for old scoring snapshots. For the new version, official Ministry content should benefit from source trust, science-education relevance, action/policy signals, and product alignment instead of a source-name override.

## Verification implications

- Domain unit cases: bilingual positive/negative terms, AI-without-education, education-without-science/AI, science policy, classroom practice, products/financing, ambiguous `agent`, age/product direction matches, and contribution caps.
- Acquisition cases: title-first hit, bounded title-miss detail probe, zero-match source, no unrelated detail-fill, rule audit metadata, English dates/timezones, and parser drift fixtures.
- Topic cases: science education outranks generic AI content; product fit contributes to the numeric total and may legitimately help an eligible event cross the threshold, but it cannot make an out-of-scope event eligible or override any hard veto; historical config preserves Ministry behavior; stable replay yields identical explanations and rank.
- Cross-layer cases: source/profile seed round trip, occurrence/event projection, score config snapshot, score persistence/API schema, OpenAPI/frontend generated contract if explanation fields change, and real PostgreSQL migration assertions if typed columns are added.
