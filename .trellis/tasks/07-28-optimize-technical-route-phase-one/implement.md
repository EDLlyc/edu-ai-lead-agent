# Technical Report v0.3 Implementation Plan

## 1. Establish the v0.3 document frame

- Update versioning, executive summary, typography, colors, spacing, and reusable LaTeX styles.
- Correct literal Markdown emphasis and wording defects.
- Preserve XeLaTeX/Overleaf compatibility and avoid external assets.

## 2. Align architecture and delivery order

- Revise the architecture principles and flow figure so authoritative-source acquisition is the
  explicit first capability.
- Keep evidence retrieval and brand retrieval separate.
- Preserve manual social publishing as a hard boundary.

## 3. Rewrite the acquisition module

- Add source registry and trust-tier definitions.
- Add RSS/API-first and allowlisted-HTML-fallback connector rules.
- Add scheduler ownership, durable run state, safe fetching, incremental collection, immutable
  snapshots, provenance, idempotency, metrics, and typed failure behavior.
- Replace the loose storage table with a precise acquisition/evidence contract.

## 4. Correct downstream technical contracts

- Clarify normalization/deduplication and event identity.
- Make scoring versioned and preserve no-topic behavior.
- Correct full-text/BM25 terminology.
- Expand generation output with claim-to-evidence bindings.
- Place deterministic validation before LLM audit and image generation.
- Align the technology table with the configured development environment.

## 5. Replace the milestone table

- Remove all P0–P4 labels and the manual-input generation demo.
- Add six ordered capability steps beginning with authoritative-source acquisition.
- Give every step a deliverable boundary and observable completion evidence.

## 6. Compile and verify

- Compile with XeLaTeX in a temporary build directory.
- Fail on LaTeX errors and inspect overfull/underfull box warnings.
- Search the source and extracted PDF text for remaining P-level labels, literal Markdown emphasis,
  obsolete runtime wording, and inaccurate BM25 claims.
- Render every page to images and inspect hierarchy, clipping, overlap, table wrapping, and page
  balance.
- Produce a separately named v0.3 PDF and verify the original `技术报告.pdf` checksum is unchanged.

## Validation Commands

```bash
sha256sum 技术报告.pdf
latexmk -xelatex -interaction=nonstopmode -halt-on-error -outdir=/tmp/edu-report-v03 main.tex
rg -n 'P[0-9]|\*\*|Python 3\.10|BM25' main.tex
pdftotext /tmp/edu-report-v03/main.pdf -
pdftoppm -png -r 120 /tmp/edu-report-v03/main.pdf /tmp/edu-report-v03/page
git diff --check
```

## Risk and Rollback Points

- Long tables or denser acquisition content may create page overflow; adjust content hierarchy and
  column widths rather than shrinking the body text below a readable size.
- TikZ changes may clip on A4; compile and inspect after each diagram rewrite.
- Keep the original PDF untouched throughout implementation.
- `main.tex` is currently untracked user-provided content; stage it only as part of the explicitly
  approved report task.
