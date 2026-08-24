# Upload AI recognition reuse boundary

## Repository evidence

- `scripts/annotate_brand_visual_assets.py` already proves a bounded Zhipu vision request using
  `glm-4.1v-thinking-flash`, a data URL, strict JSON extraction, allowlists, prompt-injection
  treatment, safe error codes, and no raw provider persistence.
- That script is synchronous, offline-only, and uses the static catalog's
  `characters/topics/poses/scene_tags` taxonomy. It must not be imported into the FastAPI runtime or
  used as the IP upload response contract.
- The runtime already validates PNG/JPEG/WebP signatures, decoded dimensions/pixels, and normalized
  image inputs. `qwen3-vl-embedding` returns a 2048-dimensional retrieval vector and cannot produce
  catalog field suggestions.
- Local settings already configure the Zhipu HTTPS endpoint and credential. A dedicated IP
  recognition feature flag/model setting must remain committed off by default.

## Selected MVP boundary

- Trigger: explicit user click after local file selection; selection/preview alone makes no call.
- Result: advisory editable values for IP character/type and bounded secondary metadata/tags.
- Authority: the later ordinary upload payload, confirmed or edited by the user.
- Persistence: none for recognition. No asset, job, database row, MinIO object, provider body,
  prompt, image bytes, fingerprint, or provider request ID is stored.
- Failure: preserve file/form state and manual upload; return only a bounded safe reason.
- UX: one pending action, visible “AI suggestion—please verify” state, stale result cleared when the
  selected file changes, and no automatic form submission.

## Suggested wire shape

```text
POST /api/v1/ip-assets/recognitions  multipart file

200 {
  status: "suggested",
  character: controlled enum,
  asset_type: controlled enum,
  emotion/action/scene/intended_use/style: bounded strings,
  tags: bounded controlled/free suggestion list,
  provider: bounded safe provider label,
  model: bounded configured model label
}
```

Disabled/provider/invalid-output failures use existing typed API error translation and never imply
that manual upload is unavailable.
