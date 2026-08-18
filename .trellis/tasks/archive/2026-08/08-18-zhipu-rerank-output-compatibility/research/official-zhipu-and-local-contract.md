# Official Zhipu and Local Contract Evidence

## Official documentation checked on 2026-08-18

1. [Chat completions API](https://docs.bigmodel.cn/api-reference/%E6%A8%A1%E5%9E%8B-api/%E5%AF%B9%E8%AF%9D%E8%A1%A5%E5%85%A8)
   - `glm-5.2` is an accepted model identifier.
   - `response_format={"type":"json_object"}` is the documented JSON output mode.
   - The API recommends explicitly asking for JSON in the prompt.
   - `thinking` is available for GLM-4.5 and newer; `do_sample=false` selects deterministic
     generation and ignores sampling parameters.
2. [Structured output](https://docs.bigmodel.cn/cn/guide/capabilities/struct-output)
   - The official GLM-5.2 examples use `response_format={"type":"json_object"}`.
   - Expected fields and JSON structure are written into the system message.
   - The documented JSON-Schema example validates client-side after parsing; it does not use a
     `response_format=json_schema` request.
3. [Thinking capability](https://docs.bigmodel.cn/cn/guide/capabilities/thinking)
   - `thinking.type=disabled` is the documented way to return the answer without a thinking pass.

## Local evidence

- `backend/app/infrastructure/ai/topic_rerank.py`: current JSON mode is correct, but the strict
  mock assumes an exact shape and all parse stages collapse to one diagnostic.
- `backend/app/application/services/topic_reranking.py`: the current system message lists field
  names but not the exact object schema or the literal reason-code enum.
- `backend/app/infrastructure/ai/copy_generation.py`: the production structured-copy path already
  disables thinking and owns a bounded one-object envelope scanner plus safe Pydantic issue
  projection.
- `backend/app/core/errors.py`: `InvalidProviderOutputError` already carries bounded, content-free
  issue codes and validation locations/types.
- `backend/app/domain/topic_rerank.py`: downstream validation already enforces full permutations,
  priority barriers, allowlisted reason codes, bounded explanations, and deterministic fallback.
- `.trellis/spec/backend/error-handling.md`: raw provider content is forbidden; bounded one-object
  compatibility must not relax Pydantic/domain validation.

## Live observation boundary

The single pre-fix synthetic call proves only that the HTTP response reached local parsing and the
current adapter rejected the result. Because the adapter intentionally discarded raw content and
collapsed parse stages, the evidence does not establish whether the response used Markdown,
prose, a wrong field, a wrong enum, or another schema difference. The fix therefore combines the
official request contract with safe stage diagnostics and validates it with at most one post-fix
synthetic call.
