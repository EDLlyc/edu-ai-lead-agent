# September 23 brand-illustration correction

The user requested a correction of only the five generic brand illustrations in
the September 23 article “从智能制造到家庭科学教育：家长如何帮孩子准备未来”. The published
news images, intro banner, footer, article copy and image positions were out of
scope. No separate vision-model review was requested.

Five new 1536 × 1024 scene illustrations were generated with the built-in image
generation tool using the existing Xiaosai robot as a character reference. They
were encoded as JPEGs below 1 MiB and stored locally under
`output/wechat-brand-illustrations-2026-09-23-v1/`. `prompts.md` records the
scene prompts and the original generated PNGs remain beside the JPEGs.

| Candidate | Existing draft image slot | Scene |
|---|---:|---|
| 0 | 2 | Child assembling a mechanical model with Xiaosai |
| 1 | 3 | Prism observation and curiosity |
| 2 | 4 | Comparing a claim with a plant observation |
| 3 | 5 | Paper-airplane test and measurement |
| 4 | 7 | Family observing sprouts and melting ice |

The existing-draft operator returned `planned`, then `same_draft_updated` with
`readback_verified=true` and `not_published=true`. A separate `reconcile` call
returned `readback_verified` without another provider write. The original
draft media ID was reused; there was no draft creation or publication call.

The first reconciliation attempt exposed an operator-only bug: it compared the
already updated draft to the pre-update add receipt before entering the readback
branch. The shared task-local operator now checks that original equality only
when no update intent exists. Reconciliation then passed. Production application
services were not restarted or redeployed.
