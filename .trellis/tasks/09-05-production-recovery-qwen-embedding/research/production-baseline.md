# Production baseline, September 5, 2026

## Read-only method

Existing edu-ai-production SSH access; observed 19:13-19:17 Asia/Shanghai. SQL used BEGIN READ
ONLY, 10-second statement timeout and ROLLBACK. Runtime settings were allowlisted; protected
.env inspection output only nonempty-assignment booleans. No provider calls, sends or writes.

## Facts

- 14 running services; API, PostgreSQL and MinIO healthy. Application image prefix 35e4405a5dfa.
  Healthz reports production/ok. Prior release commit:
  5c560da71bcbb61b765d3fe82c742cf2d5e676e1; image digest:
  sha256:35e4405a5dfa06e70a45c360d8838021e00c05938ac7f7e818378c6454d48454.
  This pass checked prefixes only; recheck full markers before mutation. Prior backup:
  20260905T100525Z, documented in the archived hotfix result.
- WeCom jobs: 95 delivered, one failed (August 6). Last delivered: September 2 12:30:02 CST.
- Dispatcher: enabled=true, auto=true, group_webhook, manual-review-before-send=false,
  slot-mode=true. Direct mode still requires copy/image quality gates.
- Content worker deliberately has WeCom flags false/no sending credentials; its
  content_copy_provider_required=true is the relevant upstream projection.
- Today's copy: morning/noon/evening each 3 review_required/copy_provider_unavailable.
  Last failure 17:02:04 CST. New runs since 18:10 CST: zero.
- All copy jobs: 156 succeeded, 33 failed, 7 queued. The queued cohort was protected historical
  state in the preceding release, not a new runnable workload.
- September 2 also had provider_request_rejected (1) and provider_input_limit (3): historical
  diagnostic leads, not established current faults.
- Acquisition morning/noon/evening success/failure: 10/1, 10/1, 9/2 out of 11 sources.
  New candidates: 10, 5, 1.
- Governance success/review/failure: 38/4/0, 30/3/0, 29/2/0.
- official_account_article_runs and official_account_weekly_dag_runs: both zero rows.
- Brand identity auto -> zhipu/embedding-3/2048; visual provider disabled; official-account
  visual semantic flag false.
- Brand vector rows: 113 Zhipu + 7 fake. Earlier active-version inspection counted 57 active
  Zhipu vectors; refresh this count before a migration manifest (not re-queried this pass).
- Article vectors: 500 near_duplicate + 500 event_assignment, all Zhipu embedding-3/2048.
  Brand visual and IP vector tables: zero.
- Content worker has no Qwen key. Protected env has no nonempty VISUAL_EMBEDDING_API_KEY,
  VISUAL_EMBEDDING_ENDPOINT, VISUAL_EMBEDDING_PROVIDER_MODE or BRAND_EMBEDDING_PROVIDER_MODE.
  This does not imply that no Alibaba account exists elsewhere.
- Slot targets: 07:30, 12:30, 18:30; preparation lead 90 minutes; late window 60 minutes;
  maximum 3 items each. Current evening expires 19:30 CST.
- Local main 1b6fa7b, with 59 unrelated dirty entries before task creation.

## Repository constraints

- backend/app/application/services/copy_generation.py:68: copy version bundle includes chat
  and prompt/rule identities, not brand provider. Changing embedding is not a retry mechanism.
- backend/app/infrastructure/db/copy_generation.py:168: enqueue missing slot/version runs only.
  backend/app/api/v1/routes/copy_generation.py:29 is daily enqueue, not slot-copy retry.
- backend/app/brand_embedding_reindex_main.py:277: development-only; migrate also activates
  ready versions. Never bypass the environment guard for production.
- backend/app/brand_visual_index_main.py:44: dry-run reports catalog counts without provider
  calls; real indexing is bounded and explicit.
- backend/app/infrastructure/db/governance_artifacts.py:681 scopes neighbor search by
  provider/model/dimensions/input policy. New Qwen queries cannot use old Zhipu vectors.
- backend/app/core/config.py:554 auto-prioritizes Alibaba visual mode. Pin brand explicitly
  before a later visual enablement unless the replacement text index is ready.
