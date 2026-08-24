# Current visual-retrieval seams

## Repository evidence

- `backend/app/domain/visual_assets.py` owns immutable `VisualAsset`, manifest validation,
  `AssetSelectionRequest`, `_RankedCandidate`, and the pure deterministic `AssetSelector`.
- `backend/app/infrastructure/brand/visual_catalog.py` owns safe manifest loading and re-reading selected
  PNG bytes after symlink/path/checksum checks.
- `backend/app/application/services/material_package.py` constructs a controlled `VisualBrief`, calls the
  pure selector before the image provider, and already persists bounded reference reasons/snapshots.
- `backend/app/domain/visual_brief.py` provides a closed, deterministic query source: category, title,
  learning goal, scene, main action, characters and allowlisted asset tags.
- The current private manifest loads 41 approved PNG assets. This aggregate is safe; names, paths and bytes
  are not copied into task artifacts.
- Existing brand-document embeddings are a separate 2048-dimensional pgvector capability in
  `brand_chunk_embeddings`; their provider/model/version identity cannot be reused for image assets.
- `backend/app/core/config.py` already fails closed around provider mode and validates the existing 2048
  dimension. New visual credentials need a separate SecretStr namespace so Alibaba and Zhipu identities
  cannot be mixed.

## Provider contract evidence

- Official Alibaba Model Studio multimodal embedding endpoint:
  `POST https://{WorkspaceId}.cn-beijing.maas.aliyuncs.com/api/v1/services/embeddings/`
  `multimodal-embedding/multimodal-embedding`.
- `qwen3-vl-embedding` accepts text and Base64 image inputs, supports independent embeddings and 2048
  dimensions, and returns dense vectors under `output.embeddings`.
- A one-attempt synthetic compatibility probe on 2026-08-21 returned two independent 2048-dimensional
  finite normalized vectors. The service did not echo a model field, so immutable identity must bind the
  fixed requested model; any echoed conflicting identity is rejected.
- No API key, workspace, host, request ID, raw response, vector or source content is retained in this
  research file.

## Minimal integration seam

1. Index each approved manifest asset once under a versioned catalog/model/input-policy identity.
2. Build one deterministic text query from `VisualBrief` outside the domain selector and obtain its vector
   before opening a database transaction.
3. Retrieve a complete compatible score map for the current catalog.
4. Pass that score map into a new selector version; hard eligibility remains authoritative and semantic
   similarity ranks only the survivors.
5. If provider or complete-index proof is unavailable, execute the literal existing selector and persist a
   bounded fallback code.

## References

- Alibaba Model Studio multimodal embedding API:
  https://help.aliyun.com/zh/model-studio/multimodal-embedding-api-reference
- Alibaba Beijing workspace endpoint contract:
  https://help.aliyun.com/zh/model-studio/beijing-access-information
