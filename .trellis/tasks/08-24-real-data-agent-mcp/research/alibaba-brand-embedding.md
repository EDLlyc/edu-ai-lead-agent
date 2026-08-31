# Alibaba Multimodal Brand Embedding

## Verified Project Capability

- The existing `AlibabaVisualEmbeddingAdapter` accepts text and PNG inputs through the Beijing Model Studio multimodal endpoint.
- The frozen identity is `alibaba-model-studio/qwen3-vl-embedding`, 2048 dimensions. Text requests use `input.contents=[{"text": ...}]` and return the same identity used by image vectors.
- The configured development credentials completed a text-only live call with a finite, non-zero 2048-dimensional vector. No credential or provider body is recorded in task artifacts.
- Existing brand active versions were created in `zhipu/embedding-3` (plus a small historical fake version), so changing query vectors alone would make provider/model-filtered retrieval unavailable.

## Project Decision

- Add a brand-specific adapter/factory that maps `BrandEmbeddingRequest` to the existing Alibaba multimodal transport. Governance event/article embeddings continue to use the existing Zhipu factory.
- Bind upload derivations, worker claims, API/content retrieval, MCP retrieval and cache namespace to the same Alibaba provider/model identity.
- Rebuild brand versions from immutable originals under the current parser/chunk/embedding-input bundle. Never relabel or overwrite stored Zhipu vectors.
- Keep old active versions until the corresponding Alibaba version is fully ready, then activate per document atomically. A partial failure leaves that document on its old active version.

Official API reference: <https://help.aliyun.com/zh/model-studio/multimodal-embedding-api-reference>
