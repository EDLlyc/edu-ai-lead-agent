# Technical Report v0.3 Design

## Deliverable Shape

`main.tex` remains the source of truth. The existing `技术报告.pdf` is preserved as the v0.2
reference. The revised source is compiled to a separately named v0.3 PDF for review.

## Narrative Structure

The report will use the following reasoning order:

1. Product problem, outcome, and non-publishing boundary.
2. Architecture principles: evidence first, brand context separate, typed/observable stages,
   deterministic gates before generative side effects.
3. End-to-end capability flow beginning with authoritative-source acquisition.
4. Detailed module contracts, with the acquisition module expanded substantially.
5. Runtime and technology responsibilities aligned with the current repository contract.
6. Capability-based construction route with explicit completion evidence.

This order makes the delivery sequence match the logical architecture rather than introducing a
generation-first detour.

## First-Step Architecture

```text
Versioned source registry
        |
Separate scheduler -> durable acquisition run
        |
RSS/API connector -> allowlisted HTML fallback
        |
Fetch policy: timeout / limits / retry / rate / SSRF controls
        |
Immutable source snapshot + provenance metadata
        |
Idempotent evidence candidate record
        |
Cleaning, deduplication, clustering, and classification (next step)
```

The acquisition stage does not summarize, score, or generate content. It proves that trusted
source material can be collected repeatedly, safely, and with enough provenance for later claim
binding.

## Source Trust Model

| Tier | Examples | First-step treatment |
|---|---|---|
| Primary evidence | Government, education authorities, schools, universities, research bodies, international organizations, first-party company releases | Eligible for evidence after successful capture and metadata validation |
| Secondary context | Reputable science, technology, and education media | Discovery or corroboration; prefer linked primary source |
| Lead only | Social platforms, reposts, anonymous/unclear aggregators | Discovery only; never final evidence |

Fetched text remains untrusted regardless of source tier. Source trust concerns factual authority;
it does not make embedded instructions safe to execute.

## Acquisition Data Contract

The report will replace the current three loose field groups with an explicit contract covering:

- source and acquisition IDs;
- original and canonical URLs;
- source tier and organization identity;
- title, publication time, fetch time, and locale;
- response/content metadata and immutable snapshot reference;
- normalized-content SHA-256;
- connector, parser, and normalization versions;
- ETag/Last-Modified or source cursor when available;
- acquisition status, error classification, retry count, and correlation IDs.

Downstream clean text and summaries are derived artifacts, not substitutes for the snapshot.

## Capability-Based Construction Route

| Order | Capability | Boundary |
|---|---|---|
| 1 | Authoritative-source acquisition and evidence ingestion | Trusted source registry, safe connectors, snapshots, provenance, durable runs |
| 2 | Data governance and event organization | Normalize, exact/near deduplicate, classify, cluster while retaining provenance |
| 3 | Topic eligibility, scoring, and selection | Hard vetoes, versioned feature scores, threshold/no-topic behavior |
| 4 | Brand knowledge and retrieval | Versioned brand corpus, separate evidence/brand retrieval, full-text + vector fusion |
| 5 | Evidence-bound generation and quality gates | Typed claims, deterministic validation, LLM audit, bounded regeneration |
| 6 | Visual generation and material delivery | Approved image generation, object storage, review/copy/download UI |

No P-level labels will remain.

## Technical Corrections

- Python becomes 3.11 and Pydantic is identified as v2.
- API, scheduler, and worker responsibilities are separated.
- PostgreSQL native full-text ranking is not mislabeled as BM25.
- Evidence and brand corpora are described as separate domains.
- Draft JSON gains typed claim/evidence bindings.
- Deterministic validation is placed before the LLM audit and image call.
- Durable artifacts, idempotency, typed failures, and manual publishing remain explicit.

## Visual Direction

- Keep an A4 editorial technology-report style rather than a presentation-deck look.
- Retain deep navy/blue as the trust color and introduce one restrained teal accent for the
  evidence-first path.
- Use Noto CJK fonts available in the environment for stable Chinese rendering.
- Improve title hierarchy, callout cards, tables, row spacing, and figure labels.
- Make the first acquisition step visually prominent without making downstream steps look
  optional.
- Avoid decorative images; diagrams and information hierarchy carry the visual identity.

## Compatibility and Rollback

- Compile with XeLaTeX locally and remain compatible with Overleaf XeLaTeX.
- Avoid shell-escape and external downloaded assets.
- Preserve `技术报告.pdf`; if the revision is rejected, `main.tex` can be reverted independently
  and the generated v0.3 PDF removed without data loss.
