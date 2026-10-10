# Prior read-only audit evidence

2026-10-10: Chromium checked 1366x900 and 390x844 versions of sources, keywords, publication,
statistics, models and layouts. Screenshots/report are in /tmp/edu-admin-frontend-audit-20261010/;
real-data source mobile screenshot is /tmp/edu-admin-review-20261010/sources-mobile-loaded.png.
The first audit adds a keyword only to local React state, changes menus and returns: the term
is lost and zero dialogs occur. Mobile publication header/table extends to x453 in a390 viewport;
source titles appear vertically one character per line. Desktop statistics coverage text is
oversized alongside the numeric value. No provider writes or real-data mutation occurred.
Frontend confirmed offset always0; server already supports offset20/page. Existing CSS has no
responsive card/table contract. Existing app has no unsaved guard reusable elsewhere.
