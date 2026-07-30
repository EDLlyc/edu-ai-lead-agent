# Milestone 2 Live Zhipu Smoke

Date: 2026-07-29 (Asia/Shanghai)

## Scope and safety

A bounded live factual-analysis call was run after the deterministic Milestone 2 Gate passed.
The input was one article already stored by the acquisition capability; no website was fetched.
The API key remained in the Git-ignored local `.env`. This record contains no credential,
authorization header, prompt body, complete source body, raw provider response, or hidden
`reasoning_content`.

## Input evidence

- Candidate: `19a15298-7ec8-4536-93e7-cec5bb6315cb`
- Source: 科技日报
- Title: 全国首个具身智能发展局揭牌
- Canonical URL: `https://www.stdaily.com/web/gdxw/2026-07/29/content_555090.html`
- Stored publication time: `2026-07-29T02:08:00Z`
- Normalization version: `normalization-v1`
- Normalized SHA-256: `3681c0c1482dbbb08ce32ab1bbe9afd9b8afc0033f1f10b881637fcce01fd850`
- Passage count: `1`
- Passage ID: `8b2eb001-d7ba-5a04-9308-db2a05de45ed`
- Sensitive-data outcome: no signal; no quarantine

## Validated structured result

The first model response passed Pydantic schema validation and deterministic passage/time checks;
no corrective regeneration was required.

- Provider/model: Zhipu `glm-5.2`
- Primary category: `robotics_embodied_intelligence`
- Additional categories: `ai_industry_application`, `ai_education_policy`
- Event date: `2026-07-28` with day precision
- Extracted facts: `5`
- Extracted entities: `7`
- Keywords: 具身智能、顺德、发展局、机器人、人工智能、智能制造、产业重塑
- Every summary/fact/entity binding referenced the stored passage ID above.

The five extracted factual points were manually compared with the stored acquisition text and all
were directly supported: the bureau's launch and national-first status; the local robot-industry
scale; the three announced plans; the AI-literacy and industrial initiatives; and the planned
industrial park and innovation center.

## Safe invocation metadata

- Prompt tokens: `1634`
- Completion tokens: `3498`
- Reasoning tokens: `2329`
- Adapter latency: `44989 ms`
- Validation corrections: `0`
- Request fingerprint: `da43e8646412c6f782f875699cc0d778a2d80bcabc93b3956b8a8df5ef292ce9`

## Result and limitation

The live smoke confirms the reviewed OpenAI-compatible JSON-object adapter works with the
configured account and `glm-5.2` on one real Chinese robotics article. This is compatibility and
single-sample factual-quality evidence, not a clustering evaluation or a substitute for the
labeled Milestone 3 dataset.
