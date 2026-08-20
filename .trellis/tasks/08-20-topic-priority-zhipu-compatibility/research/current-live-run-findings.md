# Current live-run findings

## Observed selection defect

The local 2026-08-20 fresh run used scoring `.9`, threshold `0.59`, rerank v3 and one Zhipu call.
The selected event was:

- title: `教育对口支援西藏工作会议暨教育系统援藏干部人才座谈会在拉萨召开`
- deterministic total: `0.439`
- threshold: `0.59`
- priority result: authenticated Ministry priority applied
- governed content signal: event/conference shape without a demonstrated substantive science-policy
  or science-teaching action

Root cause: `ministry-education-priority-v3` checks authenticated topic metadata and the broad
science/technology-education cohort, but not the candidate title/summary or content shape. The rule
therefore turns a source-level preference into a blanket threshold bypass.

## Observed provider compatibility defect

- candidate count: 8
- provider/model: configured Zhipu chat model
- HTTP/model calls: exactly one
- outcome: deterministic fallback
- typed failure: `invalid_provider_output`
- safe usage: prompt/completion/latency metrics were captured

The raw completion was intentionally not persisted, so its exact malformed field shape is unknown.
The correct response is not to add speculative aliases or recursive parsing. The new provider wire
should reduce model-authored structure to the only authority the model needs: a complete event-ID
permutation. Local code can derive all existing item metadata deterministically.

## Current code seams

- `domain/ministry_education_priority.py`: v3 rule currently ignores content.
- `domain/science_policy_priority.py`: existing narrow science-policy classifier already excludes
  meetings and requires topic + action vocabulary.
- `domain/topic_selection.py::_priority_state`: immutable dispatch seam for selection priority.
- `domain/topic_rerank.py`: immutable policy registry and permutation/finalization contracts.
- `application/services/topic_reranking.py`: versioned prompt builder and fallback orchestration.
- `infrastructure/ai/topic_rerank.py`: strict Zhipu payload/response boundary.

## External contract note

Zhipu documents `response_format={"type":"json_object"}` as JSON-mode output whose desired field
structure must still be stated in the prompt and validated by the client. It does not replace local
schema and permutation validation.
