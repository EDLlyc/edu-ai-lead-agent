# GLM-5V-Turbo request-dialect constraint

## Official source observations

- Zhipu model guide: <https://docs.bigmodel.cn/cn/guide/models/vlm/glm-5v>
- Zhipu API parameter guide: <https://docs.bigmodel.cn/cn/api/parameter-introduction>
- The official visual examples send image content through OpenAI-compatible `messages` and omit
  `response_format`.
- The parameter documentation limits `response_format` support to text models.
- GLM-5V-Turbo exposes `thinking` as enabled/disabled; this deterministic judge path fixes it to
  `{"type":"disabled"}` and also fixes `do_sample=false`.

## Implementation consequence

The shared transport keeps its existing `json-object-v1` profile as the default. Only the direct
Zhipu image-panel composition selects the closed `zhipu-vision-v1` profile. That profile has an
exact top-level payload (`model`, `max_tokens`, `thinking`, `do_sample`, `messages`) and offers no
free-form provider option map. Multi-image order and one-shot behavior remain unchanged.

The earlier capability attempt is retained as legacy `invalid_provider_output` evidence because it
predates diagnostic separation. New failures distinguish provider envelope/schema failures from
judge-content JSON/schema failures using closed codes only; no raw response or prompt is persisted.
