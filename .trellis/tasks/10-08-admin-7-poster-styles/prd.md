# 朋友圈海报风格选择（运营后台第 7 项）

Parent `10-08-admin-console`. Planned 11/5–11/11 (4 d).

## Today

- `NewsInfographicProducer` (`application/services/wecom_news_infographic.py`), with a mode
  switch `wecom_infographic_review_mode`:
  - strict: the model paints the scene, then `render_exact_text_overlay` draws the text with
    hard-coded colours, then `render_exact_source_footer`;
  - advisory: the model paints everything; the style is written into the Chinese prompt
    (`news_infographic_advisory.py`).
- Fixed: Noto Sans CJK, 1152×2048, the pinned character reference image.
- Versions:
  - `POLICY_VERSION`, `ADVISORY_*`, `MOMENTS_*` and `FOOTER_VERSION`.
  - `_policy_fingerprint` includes the models.
  - There is one style per mode.

## Scope

- A poster style registry: id, name, palette (background, card, accent, text), prompt style
  block, overlay colours, footer colours, sample image.
  - Today's style is `classic`; add 2–3 styles.
  - Each style is a new policy fingerprint, so images stay traceable.
- The operator picks the active style (or a rotation); the choice is stored and audited.
- Before a style can be chosen, generate sample posters from 3 recent real posts. The teacher
  approves the samples (stored), and only approved styles are selectable.
- The image audit (brand, text accuracy) stays the same for every style.

## Open

- Sample designs: the teacher picks directions (colour and layout) before we prompt-engineer
  them. Generating samples costs image-model calls; budget about 20 images per style.
