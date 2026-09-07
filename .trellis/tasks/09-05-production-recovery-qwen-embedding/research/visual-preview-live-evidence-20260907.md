# Completed isolated visual preview — 2026-09-07

## Outcome and boundary

At 11:49 Asia/Shanghai, one frozen application-case preview has completed actual generation,
final-image model review, independent gzh compliance checks and exact mobile acceptance.
`acceptance.json` says `preview_accepted=true`, `human_approved=false`, `published=false`,
`database_persisted=false`, `production_activated=false`. This is a machine-accepted local sample,
not activation of the production image pipeline or replacement of any existing draft.

The next product gate is user acceptance of the sample. Runtime changes remain uncommitted on
`release/visual-quality-preview-20260907`; Trellis Phase 3.4 commit-plan confirmation is also
pending. Do not archive the broader recovery/Qwen task or push/deploy this branch implicitly.

## Sealed inputs and code

- Source run: `1c8a0cc8-b960-4b33-82ff-e7204def40f6`.
- Article: `bd743cc6-6bab-4779-a562-dfab5f624d49`.
- Render: `d74da7be-afb5-4f90-83bc-31dd7e32856a`.
- Captured input manifest SHA:
  `1bae3a88bd68e733e082627a173fef18cf2e783533d505229435bcb7eedecf19`.
- Reviewed code archive SHA:
  `1a2a2f1533d4c8fe15eaa26819cb3efbc7d7d781af3b7bcd263e52e2762bd40f`.
- All seven runtime hashes in `visual-preview-check.md` matched both candidate and staged package.
- Independent reviewer issued SAFE-TO-RUN for this one bounded preview, not production deployment.
- A zero-call source preflight passed inside the production worker container before live execution.
- Code ran as UID/GID 999 in a standalone process from
  `/tmp/edu-ai-visual-code-20260907-ku4godTT`, isolated by working directory and PYTHONPATH.
  It did not overwrite `/app`, change `.env`, restart a service, or load a DB/queue/social client.
- Remote private input/output remain at `/tmp/edu-ai-visual-source-20260907-a1` and
  `/tmp/edu-ai-visual-preview-20260907-a1`. Preserve these paid artifacts; never rerun `--live`
  against the same intent or start an automatic replacement run.

## Actual provider evidence

The immutable physical transport ledger records exactly:

| Operation | Count | Route / interpretation |
|---|---:|---|
| Image generation POST | 5 | Existing Comfly `gpt-image-2` |
| Vision audit POST | 6 | Direct Zhipu `glm-5v-turbo` only |
| Generated image download | 5 | Returned image bytes; not extra generation |
| Task poll | 0 | All generations completed synchronously |
| Embedding call | 0 | Selection truth is `deterministic_tag` |
| Retry | 0 | Application and physical dispatch attempt fences |

Five raw generations and final body JPEGs are native 1536x1024. No square response was stretched.
Final body audit results and the independently audited 1536x654 cover crop are all accepted, with
zero returned issue codes. The deterministic quality-blocking list is empty. No numeric scores,
actual billed currency amount, human gold labels, or semantic-diversity guarantee is inferred.
The main agent additionally visually inspected all five final body images and the final cover.

Article and source JSON bytes hash-match the captured originals. The original context PNG remains
1004x620, SHA `815f1c8f352aa0da0a33c7e7df87c8c7437580b2072864c49644ea0b7f32ed8a`.
Its source/credit/unverified publication-rights/context-only labels remain; a model acceptance does
not grant publication permission for that news image.

## Local artifacts and final acceptance

Root: `output/official-account-visual-quality-preview-20260907/`.

- `edu-ai-visual-preview-20260907-a1/preview.html`: visible sample, explicitly unpublished.
- `edu-ai-visual-preview-20260907-a1/article-body.html`: clean inline-style article fragment.
- `edu-ai-visual-preview-20260907-a1/assets/`: five new scenes, new cover, unchanged news image.
- `edu-ai-visual-preview-20260907-a1/manifest.json`, `calls/`, `transport/`, `raw/`:
  immutable generation/model-review evidence; source snapshots are private.
- `mobile-check-a1/mobile-report.json`, `mobile-320.png`, `mobile-430.png`: actual Chromium
  observations/screenshots, served from hash-verified local bytes with outside network blocked.
- `edu-ai-visual-preview-20260907-a1/acceptance.json`: appended by zero-call finalization.

Manifest SHA: `312a3784238b70ecbcd929761d07860d5d3beb514b7bc30ca36558523fb4ad62`.
Content fingerprint: `23d0a06cad753f1b73aa6e863b0acf3c6d3f6f328fab07505da218e9a9246d02`.
Body SHA: `169314173ca1ecc6686190aef845a3351e343128dd0375fb614b0d114c4f5e52`.
Preview SHA: `f7bd74787da6bfc51f31ce58da931ada7e8983a5151c82ab0799277288fe975a`.

| Viewport | Loaded / failed images | Horizontal overflow | External requests | Exact copy-root |
|---|---|---:|---:|---|
| 320 | 7 / 0 | 0 px | 0 | true |
| 430 | 7 / 0 | 0 px | 0 | true |

The gzh-design validator reported complete compliance, with 134 `span leaf` nodes and no errors
or warnings. Browser helper syntax check passed. Main viewed both full-page mobile screenshots.
Finalization made zero provider calls and did not modify the manifest or image bytes. Remote
generation output retains its original unfinalized manifest; the local copy holds appended browser
acceptance. Do not reinterpret the manifest's original `mobile_validation=not_run` as tampering.

## Production protection checks

Read-only queries before and after preview showed all three original runs still ready with the
same active Article/render identities. Draft job `a13a7121-3f3e-57b0-a091-2d55741d55fb` remains
ready, three items succeeded, each with attempt_count=1, and exactly three succeeded attempt rows.
Their original completion times remain 10:24:33, 10:24:41 and 10:24:49 Asia/Shanghai.

Production remains on image
`edu-ai-lead-agent-backend@sha256:67a650de85409d9d0ada260aa2354bd32b5e9d5f83e61f2231f18cf24503ea78`.
All 14 containers were running; API, PostgreSQL and MinIO configured health checks were healthy.
No claim is made that these container checks independently prove every scheduled business outcome.

## Tests / remaining work

See `visual-preview-check.md` for full independent review and baseline failure classification.
New focused checks pass; the full backend gate is not green because existing baseline tests,
format and type failures remain. These were not hidden or fixed by unrelated edits.

AC10-AC12 for the isolated preview are evidenced above. Automatic production integration,
current draft replacement, Qwen migration, broader recovery-task completion, commit and push are
not implied by this result and remain separate gates.

## Bug analysis and prevention

1. Root cause category: cross-layer contract and implicit assumptions. Scheduled production used
   approved catalog images with generation/quality flags off, while polished local demonstrations
   used different generated-image and renderer paths. A ready article/draft did not prove fresh
   images, native geometry, final-pixel review or visual quality parity.
2. Why a switch-only repair was insufficient: the old generation adapter defaulted to square
   output, audit identity inherited the text model, and export did not itself generate or review
   new scenes. This is analysis of the evidenced architecture, not a claim that those switch-only
   fixes were attempted in this preview.
3. Prevention: explicit per-request geometry and returned-pixel validation; independent GLM model
   wiring; frozen source/paid-call lineage; final-byte model audits plus real browser acceptance.
   New implementation, adapter and replay tests enforce these boundaries.
4. Systematic expansion: production integration must verify the actual scheduled consumer,
   persisted new-visual identity, final renderer, source-photo preservation and draft handoff.
   A local preview cannot prove that path and must not be relabeled as production success.
5. Knowledge captured: `official-account-visual-preview.md` and its backend index entry were added
   identically in root and candidate specs. No `src/templates/markdown/spec/` mirror exists in this
   application repository. Spec/code commits await the required explicit commit-plan confirmation.
