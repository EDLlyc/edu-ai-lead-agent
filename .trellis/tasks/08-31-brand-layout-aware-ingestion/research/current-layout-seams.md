# Current layout seams and bounded corpus audit

## Safe corpus aggregates

The controlled private corpus contains two presentation-shaped PDFs and one interview DOCX. Only aggregate
properties are retained here:

| Input class | Pages | Local extraction | Current structured result | Main problem |
|---|---:|---|---|---|
| Platform slide deck | 48 | 2,412 usable characters; 5 blank and 31 sparse nonblank pages | 43 page parents / 43 children | Multi-card and table reading order is flattened |
| Brand/product slide deck | 50 | 1,608 usable characters; 33 blank pages | OCR: 1 generic parent / 38 children | OCR page/block structure is discarded |
| Founder interview DOCX | n/a | 6,499 characters in XML block order | 14 parents / 77 children, including 9 Q&A parents | Current parser is appropriate |

Both PDFs are untagged 16:9 presentation exports. The figures above are counts only; no title, body, path,
object key, response body, vector or query is copied into task artifacts.

## Existing code path

```text
pypdf page extraction
  -> usable_characters < page_count * sparse_text_threshold
  -> optional Zhipu /layout_parsing
  -> BrandDocumentOcrResult(markdown only)
  -> service normalize(markdown)
  -> ParsedBrandDocument(no sections)
  -> parser generic fallback
  -> one parent + bounded children
```

The first deck does not enter OCR because its total extracted character count clears the document-level
threshold even though most individual pages are sparse. The second deck enters OCR, but the service creates
no `ParsedBrandSection`, so the parser correctly applies its generic compatibility fallback and loses page
identity.

## Existing reusable capabilities

- `BrandSectionModel` already stores section kind/title/text/exact offsets and 1-based `source_page`.
- `BrandChunkModel` already stores section binding, contextual `embedding_text`, exact offsets and immutable
  hashes; retrieval already diversifies by parent.
- v3 chunking already enforces parent-local overlap, 900-character children, 600-child hard cap and a
  budget-aware fallback for pathological generic OCR Markdown.
- Zhipu brand OCR already uses private Base64 input, disabled crop/layout images, bounded response/timeout/
  attempts and typed provider failures.
- The image OCR adapter in the same module already models raw `layout_details` as pages-to-elements, validates
  page metadata, two official bbox scales, element indices/labels and content-free schema diagnostics.
- The development re-index command already creates new immutable versions and activates only ready results.
- Active brand vectors use Alibaba `qwen3-vl-embedding` at the existing 2048-dimensional brand boundary.

## Historical non-negotiables

Prior structured-chunking work established the following replay and safety rules:

- preserve `parsed.text[char_start:char_end] == raw_text` for every section and child;
- do not raise the chunk cap, truncate private content or merge across parents;
- keep provider/model/audience/validity/version filtering and weighted RRF semantics;
- use new immutable parser/chunk identities instead of relabeling existing ready versions;
- keep external calls outside database transactions and preserve old active versions until ready activation;
- never allow brand/OCR content to satisfy factual evidence (`evidence_eligible=false`);
- avoid schema changes when existing typed columns can express the durable business fact.

## Recommended boundary

The useful new fact is not “a PDF used OCR”; it is “page N contains ordered, typed visible layout blocks”.
The provider adapter should validate and project that fact once. The versioned parser should own canonical
text, page sections and exact block offsets. The chunker should consume ephemeral block spans, while the
repository continues to persist only page parents and retrievable children.

Persisting bbox now would create a migration and public contract with no current consumer. Keeping it as a
replayable parse hint achieves better retrieval and leaves region-highlighting as an explicit later task.

## Principal risks

1. Treating all landscape PDFs as slides would create unnecessary paid OCR calls; use both geometry and
   per-page sparsity, plus the existing aggregate sparse rule.
2. Reimplementing layout validation for brand PDFs could drift from image OCR; extract shared primitives and
   keep capability-specific projection policies.
3. Sorting every block by `(y, x)` can corrupt multi-column cards. Preserve provider sequence and use geometry
   only for conservative adjacent title/body grouping.
4. Falling back to Markdown when a v4 layout envelope is malformed would silently recreate the current one-
   parent defect. v4 must fail closed; frozen v3 may retain its old Markdown fallback.
5. The shared worktree is dirty. Real re-index evidence and a commit must be scoped to this task and must not
   include other agents' or the user's changes.
