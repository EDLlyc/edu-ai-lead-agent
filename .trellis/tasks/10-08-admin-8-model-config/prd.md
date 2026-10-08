# 后台模型 API key 与链接配置（运营后台第 8 项）

Parent `10-08-admin-console`. Planned 11/11–11/16 (3 d). Owner-only section.

## Today

- Everything is in env Settings (`core/config.py`):
  - Text, vision and audit: `ai_platform_base_url` / `ai_platform_api_key`, `ai_chat_model`
    (glm-5.2), `image_quality_audit_model`, `brand_ocr_model`, `image_ocr_model`,
    `ip_asset_recognition_model`. `ai_embedding_model` is validated to equal `embedding-3`.
  - Image: `toapis_*`, `comfly_*`, `image_model`.
  - Visual embedding: `visual_embedding_*`.
  - Agent workbench settings: `agent_workbench_openai_*`.
- `STRICT_VISUAL_POLICY` pins the comfly image model and the audit base URL (enforced in config).
- `get_settings()` is lru-cached. About 33 `*_main` processes read it once at start-up, so a
  change means restarting the services. Some entry points build Zhipu clients directly.

## Scope

- `model_endpoints` table: provider, purpose (chat, audit, OCR, image, embedding), base URL,
  encrypted key (same scheme as item 5), model name, enabled.
- Effective config = database row if valid, else env.
  - Processes reload it at the start of each job (no cache longer than one run), so no restart is
    needed.
  - The API and long-running workers re-read on a short TTL.
- Guards:
  - "测试连接" sends one tiny request and shows latency and the error before saving.
  - The base URL must be https on an allowlisted host pattern; no private IPs.
  - Pinned values (strict visual policy, embedding model/dimensions) are shown read-only; changing
    them needs a code release, because stored vectors and image policies depend on them.
  - Keys are write-only and shown as `••••1234`. Every change is audited (field names only).
- Roll back to the previous version with one click.

## Open

- Should operators be able to switch providers (e.g. Zhipu to another OpenAI-compatible API), or
  only rotate keys and URLs for the current ones? First cut: rotate and change the URL;
  switching providers comes later.
