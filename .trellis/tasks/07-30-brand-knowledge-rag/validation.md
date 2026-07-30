# Validation: Brand Knowledge Ingestion and RAG

## Supplied private corpus

Validated on 2026-07-30 against the files in `private/brand-materials/`. Raw private files, parsed
text, checksums, and credentials are intentionally omitted from this record.

### Text documents

| Internal title | Pages | Extracted characters | Chunks | Document ID | Version ID | Job ID | Result |
|---|---:|---:|---:|---|---|---|---|
| Sai Xiansheng brand and product introduction | 50 | 1,602 | 2 | `f5bcb13a-b0f3-4803-8b8c-476180e99035` | `c9573cc8-ca7b-4980-b45f-9c880bbc9615` | `482d80c1-b858-44aa-bebf-aa491565c469` | `succeeded`, ready, active |
| Xiao Sai AI Planet platform introduction | 48 | 2,496 | 4 | `dd1af4fc-eaa6-4734-a339-a1cb449cde91` | `0f2efa12-bdd9-4eb0-90b0-bbd107ab968d` | `b84f31e5-05f8-4e41-a126-92a6faab2481` | `succeeded`, ready, active |

Both versions use the controlled offline `fake` provider with the immutable `embedding-3`, 2048-
dimension contract. This validates the production-shaped PostgreSQL, MinIO, worker, activation,
and retrieval path without spending or exposing a live model credential.

Both PDFs are slide-deck exports with valid, unencrypted text layers. The bounded v1 parser safely
handles them without OCR. Text extraction is incomplete because many slides communicate through
images or outlined graphics: 43/48 and 17/50 pages contain extractable text, respectively. This is
acceptable for the MVP because the extracted corpus contains representative positioning, product,
audience, tone, and risk language. OCR or source PPT/DOC ingestion remains a later quality upgrade.

The supplied PDFs are about 24 MiB each. `BRAND_UPLOAD_MAX_BYTES` now defaults to the existing hard
cap of 25 MiB so these documents fit while upload, object-read, page, character, and chunk limits
remain enforced.

### Metadata and evidence boundary

- Audience is `parents`, meaning the generated Moments copy targets parents; retrieval remains an
  internal generation operation.
- Tone tags cover professional/credible, positive/warm, exploration, companionship, and technology.
- Safety tags require external verification for promotional superlatives, market/policy numbers,
  advancement outcomes, product status, certifications, and time-sensitive pricing.
- Retrieval responses retain `evidence_eligible=false`; no brand chunk can bind an external claim.

## Visual assets

The private manifest at `private/brand-materials/visual-assets.manifest.json` contains 26 validated
PNG assets with content-derived IDs, dimensions, alpha presence, character tags, and relative paths.
It is ignored by Git together with the raw assets, is marked `text_rag_eligible=false`, and is
reserved for the later image-generation/material-package task.

The manifest builder skipped all 182 `:com.tencent.wedrive.*` metadata sidecars and found no other
unsupported asset in the two visual input directories. It indexes only bounded PNG files, rejects
symbolic links, and never sends image content to the text RAG. Rebuild command:

```bash
python scripts/build_brand_asset_manifest.py
```

## Controlled generation-intent retrieval

Query intent: generate parent-targeted Moments copy about AI and science education using brand
positioning, tone, product value, and risk boundaries.

- Result count: 5; `evidence_eligible=false`.
- Both active supplied documents were represented.
- Retrieved context covered scientific spirit, curiosity/thinking/creativity, AI learning and
  creation, youth safety, parent supervision, and product capability/price claims.
- Every hit carried the version safety tags, so the later generation node can treat claims about
  leadership, first-in-industry status, policy/market numbers, outcomes, certification, current
  features, and prices as unverified until matched to stored authoritative evidence.

The fake embedding validates filtering, rank fusion, and metadata propagation, not semantic quality
of the production provider. The retrieval order placed a price-comparison chunk first for this broad
query, so the copy-generation node must use bounded contexts plus deterministic evidence/risk gates;
a later Zhipu retrieval evaluation and reranking tuning may improve relevance.

## Focused verification

- Private manifest build: 26 PNG assets indexed; 182 WeDrive sidecars skipped; zero unsupported
  files in the supplied visual directories.
- Manifest-builder synthetic validation: passed for PNG dimensions/alpha and header/trailer
  integrity, character tags, sidecar exclusion, unsupported-signature and symbolic-link exclusion,
  bounded dimensions, and `text_rag_eligible=false`.
- Ruff focused check: passed for the config change, manifest builder, and brand unit tests.
- Strict mypy focused check: passed for config, brand domain, parser, and service modules.
- Brand and manifest-builder unit tests: 11 passed with coverage disabled for the focused run.

## Final quality gate

Completed on 2026-07-30 after the final production and review edits:

- `make check`: passed. Ruff format/lint and strict mypy passed; the backend reported 232 tests
  passed with 82% aggregate coverage; OpenAPI and generated frontend types were drift-free; the
  frontend reported 3 component/accessibility tests passed; the production Vite build succeeded.
- `make doctor`: passed against healthy PostgreSQL and MinIO, Alembic head `20260730_0007`, all six
  brand-knowledge tables, and both governance and brand `vector(2048)` columns.
- `docker compose config --quiet`: passed.
- `git diff --check`: passed.
- Repository secret scan: no private-key, AWS, GitHub, OpenAI-like, Google, or live provider-key
  credential was found. Long identifier/member-access false positives were reviewed without
  printing candidate values. `gitleaks` was not installed, so bounded repository regex scanning
  was used and the limitation is recorded here.
- Git isolation preview: only the private-directory README and `.gitignore` files would be added;
  supplied PDFs, PNGs, generated private manifest, WeDrive sidecars, and other private contents
  remain ignored and untracked.

During the gate, the development doctor and two older governance migration tests were corrected to
recognize head `20260730_0007`. One pre-existing governance API integration test failed once due to
order-sensitive behavior, passed immediately in isolation, and the subsequent complete `make check`
passed all backend tests; the final gate, including the added manifest-output regression, reported
232 passed.
