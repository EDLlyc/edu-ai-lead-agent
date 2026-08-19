# Week evidence: 2026-08-10 through 2026-08-16

## Timeline from committed work and journal

- **Aug 10**: relaxed local preview copy delivery; added news framing and source links; removed topic title from formal WeCom text; added warning-only copy quality and image fallback; deployed backend automation.
- **Aug 11**: relaxed preview warning blockers and synced logging fix; repaired Comfly direct raster handling and provider wait bounds; verified and deployed the parser fix.
- **Aug 12**: compacted Moments copy defaults; deployed current-day replay boundary.
- **Aug 13**: unblocked source dates and prevented same-day duplicate delivery; prioritized science/education sources; restored tiered science/technology priority; restored CAST/EdSurge DNS but deterministic parsing remained pending.
- **Aug 14**: deployed science/technology priority release; implemented three-slot independent production and durable delivery windows.
- **Aug 15**: deployed controlled visual diversity v2; performed bounded production acceptance; image media gate passed but Zhipu OCR returned `provider_request_rejected`, so production diversity/OCR remained off with no retry or WeCom delta.
- **Aug 16**: aligned release-driver tag contract, hardened default-off retry/release evidence, added the “小赛洞察” brand-opening commit. These are included as the final day of the reporting window.

## Evidence anchors

- Content: commits `d9db4e0`, `21f3188`, `007000c`, `126129e`, `8dfa9f5`.
- Image/provider: commits `6c58689`, `0d4c2a2`, `3aa7417`, `bf5aae9`, `c66aa62`.
- Production: commits `a14847a`, `bc1d189`, `3f54be2`, `8b55533`, `7d8a914`.
- Selection/slots: commits `4bba9eb`, `6bd7a17`, `c045f17`, `3383841` and `d47a1d1`.

## Verified problem boundaries

1. CAST and EdSurge public DNS was restored, but deterministic discovery still reported `parse_failure`; the next action is a dedicated connector/parser fix.
2. Visual media checks passed, but the bounded OCR acceptance received provider rejection; production flags stayed off, with zero retries and zero WeCom/provider increments in the evidence.
3. Some production releases reused an existing dependency layer after package-source resolution failures; this is an operational constraint and should be described as a release workaround, not a product feature.

## Intended weekly narrative

The week moved the project from “content can be generated” toward “content production can be bounded, traceable, and safely delivered”: copy rules became more flexible but auditable, image provider responses became more compatible, editorial priority and three-slot lineage became explicit, and production release/rollback checks became stronger. The remaining work is concentrated in source parser completion, provider compatibility, and continued safe production observation.
