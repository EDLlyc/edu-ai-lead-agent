# Fixed-base OCR preservation evidence — September 22

The first local candidate smoke failed before transfer or production quiescence.
Its full application-tree comparison found exactly one pre-existing discrepancy
between the immutable production base and its labeled Git revision. This was a
projection error in the new builder; it is not authorization to deploy an OCR
change.

| Binding | Verified value |
|---|---|
| Production revision | `abfb89d9371d56b1fc651e9ea0a11f50bed37724` |
| Production OCI manifest | `sha256:c98c7004a19274a7897ac267784cc376f9ad41e28570de28edfd57ecee5a9bd6` |
| Base archive SHA-256 | `22512ec68fad689713a43580d2829f41f31416518737f203941a8516c4d07eb4` |
| Sole preserved application path | `infrastructure/ai/zhipu.py` |
| Final base runtime SHA-256 | `b9aa021414acc1dcb25068bac707c97da3b52cbd5fc5cb3195ed1a3174514cd9` |
| Final base runtime size | 48,896 bytes |
| Baseline and candidate Git SHA-256 | `3e63bf9d40131c3be51ee4351e8acec8832319f24ba5e5bfc9aab5e256f0345e` |

The main session verified that all other application paths/hashes and all
immutable Alembic/configuration files match. The independent reviewer located
three copies of this path in the 21-layer base: zero-indexed layers 9 and 10
contain the 66,222-byte Git implementation, while layer 11 contains the final
48,896-byte live implementation. Later layers do not replace it. The new
operator's read-only OCI decoder independently returned the exact final runtime
hash and size above.

The exception is fixed in reviewed code and repeated explicitly in the candidate
manifest. Build requires this path to be unchanged between baseline and candidate
Git and to match the pinned Git hash. No new overlay member may target the path.
The validator independently reads the already verified base layers and requires
the final image-tree expectations to use the exact preserved runtime bytes.
Additional exceptions, altered exception hashes, Git changes, or any unrelated
application mismatch fail closed.

Implementation checks before independent incremental review: 60 offline fake
tests passed, Ruff passed, strict mypy passed, and `git diff --check` passed.
No backend OCR source was edited, no dated operator was modified, and no
production action was performed by this implementer. Final layer-semantics
review and subsequent committed-candidate rebuild/smoke remain main-session
release gates.
