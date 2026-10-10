# Admin usability — approved frontend review

## Goal and authorization

Make the existing console readable on phones and prevent routine navigation/data-volume issues
from losing operator work or hiding articles. The prior turn inspected real desktop/mobile pages,
reproduced defects and proposed this next batch. The user approved that summary with
“好的，请你处理。” This is implementation authorization; no repeated planning consent is needed.
Retain the existing white/teal identity and the previous reliability release behavior.

## Requirements

- U1: At 390/768/1366 px, the shell, account selector, forms and actions fit the viewport. News
  sources and publication records become readable labelled mobile cards rather than one-character
  columns. Other wide data tables must remain usable with intentional contained scrolling/cards.
  Evidence: audit mobile publication/source screenshots, Admin.module.css mobile rules.
- U2: Warn before discarding edited forms on menu navigation, browser back/forward, reload/close,
  logout and explicit cancel. At minimum protect keywords, source editing and credential/account
  forms. Cancelling navigation preserves values; saving/discarding clears the warning. Do not
  persist credentials or unsaved content to browser storage. Evidence: keyword addition vanished
  after menu change with zero confirmation dialogs (audit/report.json).
- U3: Show draft/published total and allow access beyond 20 entries. Use existing offset API;
  switching account/tab/page must not show or act on stale data. Loading/error/retry and final
  page behavior must be clear; preserve uncertain-publication occupancy and explicit confirmation.
  Evidence: WeChatPublishPage.tsx:112 loads offset 0; admin_wechat.py:207/250 fixes page size 20.
- U4: Statistics cards emphasize the numeric value; missing-day/partial labels remain explicit
  but secondary. Keep real zero distinct from no/partial measurements and all date semantics.
- U5: Make controls and human-reconciliation forms consistent, spacious and accessible; show
  textual status badges (unknown amber, failure red) rather than painting whole rows red.
- U6: Persistently identify production/demo/unconfigured environment using explicit configuration;
  do not infer data source from hostname, build mode or successful login. Demo must visibly state
  simulated/read-only data. An unconfigured build must never claim it is production.

## Acceptance

- Browser 390/768/1366 viewport checks show no page horizontal overflow with long titles/names;
  mobile source/publication actions remain visible and accessible.
- Unsaved guards cover leave/cancel/stay/save/failed-save and multiple history entries; no secrets
  enter URL/storage. Session expiry still forces login without saving credentials.
- 45 fake drafts/published records paginate correctly, end after the last entry, preserve total,
  and isolate stale/delayed responses across accounts and tabs. No duplicate publication request.
- Statistics show large values plus compact coverage labels; keyboard focus and readable form
  labels survive responsive layouts. Existing admin behavior tests still pass.
- Explicit demo/production/unknown badge cases pass; isolated demo is refreshed with final build.
- Full frontend tests, lint, types, contract parity, both builds, independent review and browser
  acceptance pass. Record evidence and commit scoped work.

## Scope boundaries

Frontend only using existing API contracts. The overview dashboard, new backend pagination/search,
production rollout, real publication, model probes and public domain configuration are deferred.
Production remains unchanged. New UX builds upon unshipped reliability changes (0060/0061), so
its eventual production release must include that prerequisite backend before the new frontend.
