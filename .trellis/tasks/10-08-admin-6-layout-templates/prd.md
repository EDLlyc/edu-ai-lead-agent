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
