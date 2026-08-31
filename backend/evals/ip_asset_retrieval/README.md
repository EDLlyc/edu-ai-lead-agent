# IP asset retrieval evaluation

This provider-free suite compares the frozen V2 direct-score blend with V3 weighted RRF using
sanitized rank observations. It does not call an embedding provider, inspect the live IP library,
or claim online user effectiveness.

Run `python -m evals.ip_asset_retrieval.runner --check` from `backend/`. Use
`--write-canonical` only when the reviewed dataset or production ranking policy intentionally
changes.
