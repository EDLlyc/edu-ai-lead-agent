# 公众号文字排版模板选择（运营后台第 6 项）

Parent `10-08-admin-console`. Planned 11/3–11/5 (2 d).

## Today

- Live style: Editor Handoff V2 (`domain/official_account_editor_handoff_v2.py`,
  `render_editor_handoff_v2_body`, inline CSS), colours from `XIAOSAI_GZH_THEME`.
- Other real renderers: Editor Handoff v1 and the local field-guide v7 (`render_wechat_html`).
  Five more `STYLE_VERSION`s exist only in demo scripts.
- No selection: each version is a code constant.

## Scope

- A template registry in code (id, name, renderer, theme tokens, preview fixture). Start with
  2–3 templates: today's V2 plus 1–2 colour/typography variants built from the V2 renderer with
  different theme tokens.
- An operator picks the template per account (after item 5) or globally (before).
  - The choice is stored, audited and recorded on each article version (`style_version`).
- Preview renders a stored article with each template (mobile width) before switching.
- An invalid or unknown template id falls back to V2.

## Open

- Does the teacher have reference layouts they like? Their samples decide the variants.

## Built (2026-10-09)

Scope was narrowed to colour schemes on the live V2 renderer. Layout or typography variants wait
for the teacher's reference layouts (the open question above).

- `domain/official_account_layout_templates.py`: 4 templates.
  - 小赛蓝 (default) is the identity, so an account that has not chosen gets byte-identical drafts.
  - 青绿, 暖橙 and 墨黑 map each of the 12 colours the renderer emits to their own.
  - Text colours keep ≥ 4.5:1 contrast, or the original contrast where that was lower.
  - Banner images keep their colours.
- Migration 0057 adds `wechat_accounts.layout_template_id` (default `xiaosai-blue`).
- Draft upload: `WeChatOfficialAccountDraftOnlyService(layout_template_id=…)` applies the template
  right after the rights-notice rewrite, before images are uploaded.
  - The single-edition consumer looks up the account by its fingerprint.
  - An account not bound in the console keeps the renderer colours.
- An edition's template is pinned in the draft journal (`single-<id>-layout.json`) at its first
  attempt. Every write intent records the body, so a retry after a switch must keep the old one.
- API (editor): `GET /admin/wechat/layout-templates`, `GET …/{id}/preview` (a real V2 sample body
  with placeholder images), `PUT /admin/wechat/accounts/{id}/layout-template` (audited
  `wechat_account.layout_template_set` with the template name).
- Page 公众号 · 排版模板: radio cards with swatches, a sandboxed `srcdoc` preview at phone
  width, and enable per account. The production CSP allows the frame (checked in the browser).

## Tests

- Unit: the sample uses exactly the renderer colours; default/unknown are the identity; templates
  only swap colours; contrast; delivery applies the template; a retry keeps the first template;
  no choice gives byte-identical content.
- Integration: list / preview / 404 / 422 / write guard / audit; the worker lookup by fingerprint.
- Frontend tests (axe without frames); browser smoke incl. the CSP and a 390 px viewport; gate PASS.
