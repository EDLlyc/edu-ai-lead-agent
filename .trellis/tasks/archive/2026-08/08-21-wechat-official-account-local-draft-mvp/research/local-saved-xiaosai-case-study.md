# Research: 本地保存的赛先生科学公众号案例

- Source: `C:\Users\12297\Downloads\AI时代，科创教育为什么是孩子的底层竞争力？.html`
- Linux mount: `/mnt/c/Users/12297/Downloads/AI时代，科创教育为什么是孩子的底层竞争力？.html`
- SHA-256: `455512eee644916eb1e8ca7f7d416974b5017ee5f2ed9b5eb58550037ee243e3`
- Analyzed: 2026-08-22, fully local and offline
- Privacy/copyright boundary: do not copy the raw HTML, downloaded assets, QR code, mascot, or long passages into the repository. Persist only structural measurements and original implementation decisions.

## Verified document facts

- Title: `AI时代，科创教育为什么是孩子的底层竞争力？`
- Account: `赛先生科学科创中心`
- Publish time in the saved page: `2026年8月21日 10:00`
- Body: about 3,741 non-whitespace Chinese/text characters.
- Structure: five numbered `PART` chapters, 123 paragraph nodes and 214 nested section nodes. The large node count comes mainly from editor-generated wrappers, not semantic complexity.
- Visuals: 16 image elements, including seven GIF declarations. The saved resource folder is incomplete for lazy-loaded media, so the offline visual audit used the text/layout DOM and the six locally available image files only.
- Editor signature: 15 blocks declare `data-tools="135编辑器"`.
- Dominant typography: 15px body, then 16px/14px; line-height 1.6 is most common.
- Dominant alignment: left, followed by center; only a small number of blocks use justified text.
- Dominant article colors: red `#d82821`, dark blue-gray `#445b6a`, yellow marker `#fffaa3`, cyan `#90efff`, blue gradient `#0776ff` to `#838eff`, plus pale gray panels.

## Content architecture

The article uses a conversion-oriented educational explainer sequence:

1. Start from a current education event and immediately translate it into a parent-facing question.
2. Promise a short reading map of the issues a parent actually cares about.
3. Explain the macro change first: what AI changes in education.
4. Introduce a counter-intuitive central judgment: stronger AI makes inquiry and creation more valuable.
5. Turn the judgment into a scan-friendly capability list.
6. Connect the public argument to the brand's curriculum/product system.
7. End with three short pieces of advice and then a strong conversion CTA/QR block.

The first-screen contract is particularly useful: event or scene -> why it matters to this parent -> what the article will answer. The numbered `PART` ribbons, compact subhead cards, marker highlights, capability list, and final three-sentence summary make a long article scannable.

## What to adopt

1. **Parent relevance before exposition.** The first screen should answer why the reader should continue.
2. **A visible reading map.** Derive 3--5 parent questions or section promises from governed article headings.
3. **Stronger chapter identity.** Use a consistent `PART 01` rail and one informative heading, not a generic decorative title.
4. **Judgment/capability/action hierarchy.** Separate central judgment, evidence/explanation, and practical action visually.
5. **A concise ending.** Deterministically split the governed conclusion into up to three numbered takeaway cards without inventing new text.
6. **Consistent brand recognition.** Use the project's original science-inquiry cover and a stable palette; do not copy the case's mascot or banner artwork.

## What not to adopt

- Do not copy the raw design, mascot, banner, QR code, GIFs, wording, claims, or course promotion.
- Do not state blanket claims such as AI being unable to ask questions or create knowledge unless governed evidence supports the exact statement.
- Do not copy unverified policy dates, award rates, admission benefits, scale claims, or student outcomes.
- Do not use anxiety CTAs such as children losing at the starting line.
- Do not reproduce the case's five-plus competing accent colors, pervasive bold/red emphasis, or 16-image default. They make the page lively but visually noisy and fragile offline.
- Do not introduce remote fonts, editor scripts, animations, QR codes, public-account APIs, or publishing capability.

## Original v4 translation

Use an original **science field guide / editorial lab notebook** direction:

- Warm ivory page and deep science ink remain the reading base.
- Deep science blue is the primary chapter color, cyan is the information accent, and amber is the single attention marker. Vermilion remains reserved for review warnings, not normal article emphasis.
- Signature move: a compact `PART 01` data rail attached to each informative chapter heading.
- First screen: title/digest/byline followed by `家长先看` and a 3--5 item reading map derived from section headings.
- Callouts become `关键判断` or `家庭实践`, with evidence/action cues, rather than decorative quotation boxes.
- Conclusion becomes `给家长的三句话`, using only deterministic sentence splitting of the existing conclusion.
- Keep 15px body text, 1.85--1.9 line height, controlled paragraph splitting, safe HTTPS sources, one body-media placeholder, no external resources, and AA contrast.

## Generation-rule changes

Version the live prompt/rules instead of mutating existing identities:

- Open with a governed event, observable family scene, or parent question. Never invent a current event.
- State one central judgment and explain why it matters now.
- Use a reader path such as context -> judgment -> capability/evidence -> family action -> boundary/next step.
- Treat absolute AI capability claims, policy claims, awards, admission outcomes and numerical effectiveness as external facts requiring direct evidence.
- Prefer specific child actions and visible evidence over abstract ability claims; concrete named cases require authorized evidence.
- Close with up to three calm, actionable parent takeaways. No anxiety, forced conversion, QR instruction, publication instruction, or unsupported superlative.

Suggested new identities:

- `official-account-generator-v3-parent-field-guide`
- `official-account-rules-v3-parent-field-guide`
- `wechat-html-renderer-v4`
- `wechat-inline-science-field-guide-v4`
- `wechat-science-field-guide-template-v4`

Historical generator/rules v1/v2, renderers v1/v2/v3 and local adapter v1/v2 must remain replay-compatible.
