# Admin typography and responsive readability

## Goal and approved scope

Make the existing operations console easier to read and navigate on desktop and phones. The user
reviewed the five-point proposal (fonts/weights, size hierarchy, concise guidance, table/action
hierarchy and expandable mobile navigation) and replied “好的，请你处理”. This also answers the
previous task-creation question. Proceed with that concrete approved scope; no new product choice
or repeated permission is needed. Keep the current light/teal direction.

## Background and evidence

Current mainline is ed73d9d. Production admin bundles are from f062b82 and both previews run at5180
(production) and5181(read-only fixtures). Six-page desktop1440/mobile390 review found: headings20.8px
versus body16px; declared700 Chinese headings render regular Noto in the local browser while Latin
is heavier; mobile navigation884px wide on390px screen, hiding the current model/audit item; model
help pushes the first card to481px. There is no overall horizontal overflow.

## Requirements

- R1: Use a coherent admin-scoped Chinese sans-serif font stack and working weight fallback. Page
  headings24–26px on desktop and22–24px on phones, section headings18px, body15–16px, secondary
  text13–14px; inputs remain comfortably readable on phones. Preserve article-preview typography.
- R2: Show current page in a visible mobile navigation control. It expands/collapses an accessible
  grouped menu with no horizontally hidden destinations. Desktop retains its persistent sidebar.
  Preserve role filtering, history, unsaved edits and logout/session behavior. Successful navigation
  collapses the menu; cancelling an unsaved-change confirmation retains the form/current route.
- R3: Shorten model/template introductory guidance and place secondary instructions in a native
  disclosure. Keep state/failure/unknown-result messages, first-upload/retry rules and publication
  safety instructions visible or clearly reachable without changing their meaning.
- R4: Use consistent spacing, card/header/table alignment and clear primary/secondary/destructive
  action styling. Keep source links, complete audit descriptions, numeric/coverage meanings and
  controls available. No truncation that hides operational facts.
- R5: Verify browser layouts at390/768/1366+px and320px/zoom reflow, with long labels and keyboard
  navigation, then update the production frontend assets and existing demo/production previews.

## Acceptance

A1/R1: Chinese headings visibly separate from body, real browser confirms scoped weight synthesis;
no font downloads or changes to other app entrypoints/iframe article output.
A2/R2: Direct phone entry to models/audit shows current-page label; all permitted links reachable
without horizontal scrolling; expand, Escape/focus, accepted/cancelled dirty navigation and resize
work; hidden links are not keyboard focusable.
A3/R3: First useful content appears earlier on phones; secondary help expands through native
keyboard controls; published/unknown safety and operational load errors remain unambiguous.
A4/R4: Tables/cards/actions have consistent hierarchy, no clipping or page overflow at target widths.
A5/R5: Frontend lint/types/tests/API parity/build and independent review pass; production update
backs up previous assets, verifies exact hashes and changes no backend/container/config/credentials.

## Out of scope

Backend/data/API/schema changes, model calls/key rotation, publishing/upload/sync mutations,
new dashboard or poster features, public HTTPS, account/password changes and other frontend apps.
