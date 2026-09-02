# Codex Seed V2 labeling record

## Review boundary

- On 2026-09-02, Codex visually re-opened all 41 approved corpus images before finalizing Seed V2.
- The review used safe `catalog_ref` identity and the approved image corpus. Per-query live rank,
  cosine, RRF score, online behavior and provider output were not opened during labeling.
- The same AI authored and reviewed these labels. This is an internal consistency pass only, not
  independent review, human Gold, human-human agreement or human alignment evidence.

## Corpus landmarks used for the near-miss audit

The asset numbers below are the `assets.v1.json` order (sorted by `catalog_ref`), not the separate
contact-sheet helper order used by `_refs()` in `authoring.py`.

- Asset 19 is the only clear Xiao Sai + Sai Xiansheng space-station scene.
- Assets 17, 32 and 38 are Sai Xiansheng astronaut near-misses without that complete duo scene.
- Assets 24 and 28 are duo time-machine scenes; asset 28 explicitly shows reading.
- Asset 13 shows the duo running together; asset 5 shows them moving toward each other.
- Asset 36 shows three instances of Sai Xiansheng, not a third IP character.
- Assets 39, 21, 33 and 34 provide microscope, reading, exploration and mechanical-equipment
  partial evidence respectively.
- Asset 20 contains a small `小赛AI` watermark, but its visual subject and manifest identity remain
  Sai Xiansheng. Visible text does not override subject identity.

These landmarks were mapped back to public `catalog_ref` values before authoring grades. All 24
additive challenge rows have only grade 0 or 1; none is treated as a usable grade-2/3 answer.

## Frozen and additive identities

Seed V1 remains immutable history:

- assets: `9399146b747a5028052254cb8f5bf6934b9712dba31a1c48cba58f802640a506`
- queries: `637a4f155beeae969353d6fb7fafb7a555e2bb695eebf91ef1c9cec6644e7e98`
- seed: `8bf85e957b21658dbb2de28d6c735927605571170a1a05cccf61339a61715165`

Seed V2 contains exactly 124 queries, 30 no-answer cases and 5,084 grades. The 24 additions use an
18-dev / 6-holdout split and cover six challenge kinds. The blind risky-slice pass records 14 V1
grade changes with bounded reason codes in a separate ledger; V1 bytes were not rewritten.

No live or paid embedding provider was invoked while creating this record. A future authorized live
run must retain the safe run manifest and must not be described as human or online-effectiveness
evidence.
