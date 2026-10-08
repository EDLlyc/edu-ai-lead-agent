# Qwen3-VL：配图质检 + 新素材自动打标签（本地评测）

## Source (2026-10-08, owner): "1，2，请你处理。"

Qwen3-VL chat models are available to the local DashScope key (`qwen3-vl-plus`, `qwen3-vl-flash`,
OpenAI-compatible `/compatible-mode/v1/chat/completions` on the same host as the visual embedding
endpoint). Local and offline only; no production change.

## Part 1 — generated image QA

Production checks only that an image exists and has valid dimensions; the content audit is
`not_configured`. A Qwen3-VL judge looks at the generated image with the plan (cast, subject) and
the reference images, and reports: wrong character identity (e.g. Xiaosai drawn as Sai), extra or
missing characters, a prop that does not fit the subject, garbled text, overall usable.
Gold set: ~48 production images labelled by the owner on a local page (AI labels are drafts, not
gold). Metrics: per issue and overall precision / recall, false-alarm rate on clean images, both
models, cost and latency. Decision later: shadow (log only) first.

## Part 2 — new asset labelling

Qwen3-VL proposes the manifest labels of an action/identity image (characters, props, pose, …).
Evaluated against the current manifest labels of the 41 assets (human-confirmed). A local script
drafts labels for a new PNG for a person to confirm.
