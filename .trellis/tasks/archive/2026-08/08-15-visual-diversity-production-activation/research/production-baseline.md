# Production activation baseline research

## Confirmed repository contracts

- `docs/operations/production-server-migration-runbook.md` requires a separate live authorization,
  one approved news item, one provider path, no WeCom send, exact v2 title/OCR checks, and simultaneous
  diversity/OCR enablement only after acceptance.
- `retry_material_package_image` only requeues an existing artifact and cannot change its v1
  reservation into v2; it is not an acceptance seam.
- The copy version fingerprint excludes image versions, so enabling diversity cannot safely create a
  second package for an already packaged draft.
- A natural slot can select 0--3 items and automatic delivery can reconcile ready packages; using the
  next production slot would not enforce a one-image/no-send budget.
- A restored database clone plus a separate bucket can reuse the production material repository and
  worker without writing acceptance state into production. An accepted copy with no delivery job is
  the narrowest valid input because it needs no copy/model regeneration and cannot represent a sent
  package.

## Read-only production facts captured during planning

- Runtime commit is `7d8a9142d3195ce5d0df8e62252a74d99229a1bc`; migration is
  `20260815_0021`.
- Image generation is enabled with Comfly / `gpt-image-2`; AI/OCR capability is configured through
  the existing Zhipu provider. Image max attempts is currently 3; image quality audit defaults false.
- Diversity and OCR flags are absent from `.env` and therefore resolve false.
- Nine accepted-copy/successful-image packages currently have no WeCom delivery job and satisfy the
  deterministic input eligibility query.
- The production task deployed 0021 with zero visual plan/similarity rows and preserved the prior
  delivery baseline; no live controlled image has yet been generated.

## Operational conclusion

Use one newest eligible input only inside an isolated clone, cap image artifact attempts at two, and
stop production delivery/content processes before the live call. This is safer and more faithful
than an old-image retry, a generic smoke prompt, or waiting for the next multi-item production slot.
