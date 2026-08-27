# gzh-design adaptation evidence

Audit date: 2026-08-27. This record captures the exact local design baseline used for planning. It
does not make the runtime depend on a personal Codex skill installation.

## Baseline assets

- Theme source:
  `/root/.codex/skills/gzh-design/references/theme-xiaosai-moyu-layout.md`
  - bytes: 44,655
  - SHA-256: `2492a7dbab724ac60de92cdb0e4af7daa9a1d92eaeed85492d0f268858863688`
- Validator:
  `/root/.codex/skills/gzh-design/scripts/validate_gzh_html.py`
  - SHA-256: `de21aa3decac10c6ef89040bdc4e19930dbed33d6ccf7bc963b744c53da01185`
- Approved clean V4 body:
  `output/official-account-gzh-design-xiaosai-v4-brand-palette-20260826/article_排版_小赛蓝原版结构(xiaosai-moyu-layout).html`
  - bytes: 39,379
  - SHA-256: `b031c69247b0acddf216cf8931bb4fef899d693470ba07849a5273e4e2737e28`
- Approved V4 preview SHA-256:
  `a5870eebfd2f4de77e1cb653c20f25c6039726b88e078f3ad1124ea1d19aa089`
- Approved V4 ZIP SHA-256:
  `96650bae4ed6e96d0cc9c86f2e3ab30c84769e12791f8419d5993844e3f83452`

The validator was rerun during planning. It reported 218 `span leaf` wrappers and complete
compliance, with no ERROR or WARNING.

## Required runtime-independent rules

- The copyable artifact is a pure `<section>...</section>` body fragment. It has no doctype,
  `html`, `head`, `body`, `style`, `script`, or preview button.
- Styles are inline. `class`, `id`, event attributes, CSS variables, grid, external CSS/fonts and
  fixed/absolute/sticky positioning are forbidden.
- Visible text is wrapped by `<span leaf="">` so pasted styling survives the editor boundary.
- The preview shell may own a copy button/script, but neither can be inside the copied body root.
- Images use `max-width:100%;height:auto;display:block;margin:0 auto`; small images are not stretched
  with unconditional `width:100%`.
- A single article uses one theme plus its allowed common components. The approved structure stays
  the original `moyu` layout while colors use the Xiaosai palette.
- Headings are sequentially numbered; the directory selects three core sections; one to three
  existing phrases per prose paragraph receive deterministic underline emphasis. Rendering must not
  invent, delete, or rewrite substantive article content.
- Final local acceptance must run the installed validator to 0 ERROR/0 WARNING, but project code and
  CI must own equivalent deterministic checks and cannot require `/root/.codex/skills`.

## Theme vendoring boundary

Implementation may curate only the approved Xiaosai theme tokens/component skeleton needed by the
deterministic Article Package renderer. It must record a project-owned theme fingerprint and tests.
It must not read the skill path at runtime, accept arbitrary theme files, or expose a general HTML
template upload feature.
