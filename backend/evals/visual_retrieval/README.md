# Visual retrieval offline evaluation

This six-case provider-free fixture covers text, image, synonym, unrelated, stable-tie, and provider
failure behavior. It exercises the production selector with synthetic metadata and no private image
or network access. The canonical report also freezes active
`brand-visual-embedding-input-v2`; deterministic raster normalization and provider-envelope bounds
are exercised by provider-free unit and contract fixtures rather than copying private images here.

```bash
cd backend && python -m evals.visual_retrieval.runner --check
```
