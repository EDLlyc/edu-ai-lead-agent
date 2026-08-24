# Component Guidelines

## Component contract

Build function components with explicit TypeScript props and composition. Keep data loading in
feature hooks/page containers and rendering in focused components. The implemented
`features/brand/BrandKnowledgePanel.tsx` follows this boundary; material-package examples below
remain the next-slice target.

## Component boundaries

A material-package page should compose sections rather than becoming one large component:

```tsx
type MaterialPackageViewProps = {
  readonly package: MaterialPackageViewModel;
  readonly onCopy: (text: string) => Promise<void>;
  readonly onDownloadImage: () => Promise<void>;
};

export function MaterialPackageView({
  package: materialPackage,
  onCopy,
  onDownloadImage,
}: MaterialPackageViewProps) {
  return (
    <article aria-labelledby="material-package-title">
      <TopicSummary package={materialPackage} />
      <CopywritingPanel text={materialPackage.copywriting} onCopy={onCopy} />
      <ImagePanel image={materialPackage.image} onDownload={onDownloadImage} />
      <EvidenceList sources={materialPackage.sources} />
    </article>
  );
}
```

Use domain-specific names. A component should have one reason to change: data orchestration,
rendering a section, or implementing a reusable interaction primitive. Do not add memoization until
profiling or a stable-prop boundary justifies it.

## Props and composition

- Define props next to the component unless they are a shared public feature contract.
- Mark input objects/arrays `readonly` and do not mutate props or query-cache data.
- Prefer discriminated unions for meaningful visual states instead of many booleans.
- Pass IDs and callbacks only when the child does not need the whole view model.
- Use `children` for visual composition, not to hide feature dependencies.
- Avoid optional props that make an invalid or ambiguous state possible; provide explicit variants.

Map generated API data to a view model in the feature layer when formatting, fallbacks, or state
interpretation is needed. Do not scatter wire-field transformations through JSX.

## Material-package experience

The internal package view must make these items easy to inspect:

- selected topic title, category, source trust, and generated date/time;
- WeChat Moments copy, parent takeaway, and sales interaction prompt;
- image preview, meaningful alternative text, and download action;
- original evidence links and, where appropriate, which claims they support;
- run, deterministic-validation, and LLM-audit state, including safe error guidance.

Copying and downloading are convenience actions. Keep the text selectable and the source URLs
normal links. There must be no automatic social publishing control. Label the workflow explicitly
as manual review/copy/download when ambiguity is possible.

## Local official-account explanation

The development-only official-account workbench maps generated OpenAPI fields to one typed view
model before rendering. It labels `multimodal` versus deterministic fallback, shows the closed
semantic reason, query/selector versions, bounded provider identity, and per-image selection method
and similarity band. When the generated-visual capability is enabled, it also maps the safe
`generated_visuals[]` projection into an ordinal/section/status summary and labels the
`generating_body_visuals` stage with ready/total derived only from safe results and the planned
body-image count. The planned count remains available before media staging because the API derives
it from the persisted selection snapshot; the UI must not substitute `generated_visuals.length`
or staged media count. It displays bounded block position/kind and uses the API-provided section/block
purpose for semantic image alt text; it never reconstructs a prompt or private reference from
those fields. Gallery composition stays exact 3:2 because it renders the same persisted publication
bytes resolved by final HTML/export. Never render raw similarity, query text, vector, private catalog ID/path or filename,
prompt, storage descriptor, or provider body. State in visible text that semantic selection and
automatic image generation are not human editorial approval; pending/rejected/approved article
review controls and copy-ready eligibility remain a separate aggregate. The panel keeps the
permanent local-simulation/no-WeChat boundary and provides no publish action.

When the ordered timeline contains eight processing stages, its wide-screen grid must also expose
eight tracks; keep the existing responsive single-column override for narrow screens. Test both the
`generating_body_visuals` ready/total label and the last-stage presence so a newly added stage does
not silently wrap because of stale CSS column counts.

## Accessibility

- Use semantic landmarks, headings in order, lists, links, buttons, and status messages.
- Use a native `<button>` for copy/download actions, not a clickable `<div>`.
- Keep visible keyboard focus and a logical tab order; never use positive `tabIndex`.
- Announce copy success/failure through an `aria-live="polite"` region without stealing focus.
- Give icon-only buttons an accessible name and decorative icons `aria-hidden="true"`.
- Give generated images meaningful alt text based on approved package metadata; use empty alt only
  when an adjacent equivalent description makes the image purely decorative.
- Do not rely on color alone for queued, passed, warning, or failed states.
- External source links must identify their destination; opening a new tab requires appropriate
  `rel` attributes and a visible/accessibly announced indication.
- Respect reduced-motion settings and support browser zoom/reflow.

## Styling

Use project tokens and CSS Modules as the initial default. Prefer layout primitives (grid/flex,
logical properties, `gap`) over hard-coded offsets. Components consume semantic tokens such as
surface, text, warning, and focus rather than embedding brand hex values throughout JSX/CSS.

The product is an internal verification tool: readability, provenance, and action clarity take
priority over decorative animation. Responsive layouts must keep copy and sources usable on narrow
screens even if the primary target is desktop.

## Loading, empty, and error states

Every asynchronous view defines loading, not-found, no-topic, cancelled, failed, and ready
behavior. Loading indicators have accessible text. Errors show a safe user action and retain the
request/run ID for support. Do not render stale package content as if it belonged to a newly
selected run.

For the three-slot board, render all three stable columns even when a column is disabled or has no
items. Keep each 0--3 selection in its own card with its own copy/package/delivery status and source
links; a sibling failure must remain visually local. Show target/expiry and explicit unfilled
reasons in text, preserve logical heading order, and ensure date input and resource links work by
keyboard. Once the immutable delivery expiry is reached, a queued/running run that never completed
and a selection without a started delivery must project `expired`, not remain indefinitely
`preparing`; confirmed failed, delivered, or unknown results retain their explicit state. Reuse the
material-package visual vocabulary without adding a publish action.

## Avoid

- One component that fetches, transforms, renders, copies, downloads, and polls.
- `dangerouslySetInnerHTML` for source or model content.
- Using audit color/status without text.
- Toast-only confirmation that is unavailable to assistive technology.
- Disabling source inspection after a package is accepted.
- A “post” or “publish” component that violates the manual-in-the-loop boundary.
