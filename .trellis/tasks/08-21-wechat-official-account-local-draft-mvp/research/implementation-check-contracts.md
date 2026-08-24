# 实施与复核硬合同摘录

本文件只提炼本任务需要、但位于大型规范中的合同。完整权威文本仍在 `.trellis/spec/`；若实现遇到
未覆盖场景，应打开对应原规范核对，而不是从本摘要外推新行为。

## Pipeline boundary

- 系统没有自动社交发布阶段。新增代码不得添加公众号凭据、发布 SDK、自动定时发布或“立即发布”
  API/UI；本地 draft 必须始终标为 simulation，且不能改变现有素材包/企业微信状态语义。
- 长文事实只能消费持久化 evidence；品牌知识只约束语气、品牌陈述、安全和视觉，不可作为外部事实
  evidence。未知、跨类型或未绑定 claim 必须 fail closed/review required。
- 历史短文 prompt/schema/fingerprint 和 `MaterialDraft` 保持冻结。公众号文章使用新的 typed origin、run、
  version、attempt、render、media 和 draft lineage。
- 模型前后都是确定性边界：输入集合和版本先冻结，输出通过严格 schema、provider/model 身份与本地
  规则验证后才可持久化为 active version。不得保存 raw prompt、response 或 model reasoning。
- Artifacts are immutable/versioned. Replay reuses the same fingerprinted result; policy/model/version changes
  form a new identity rather than overwriting history.

## Worker, transaction and retry boundary

- API only enqueues durable work. Claim in a short transaction, call LLM/storage/adapter outside the transaction,
  then persist under the same lease token in another short transaction.
- Use bounded attempts, heartbeat and `FOR UPDATE SKIP LOCKED` or equivalent lease-safe claiming. Lease loss must not
  allow a stale worker to overwrite a later result.
- Retry only typed transient failures. Invalid input/schema, provider identity mismatch, unsupported claim,
  deterministic safety failure and audit rejection are terminal/review outcomes, not generic retries.
- Persist each successful child stage before the next call. On restart, recompute expected fingerprints and skip the
  matching article/render/body-media/cover/draft artifact.
- An ambiguous draft-creation transport result is `result_unknown`; never automatically create another draft. An
  explicit retry is limited to confirmed retryable failure and must refuse unknown/ready/review-required states.

## Persistence and migration boundary

- PostgreSQL is the source of truth. Core source/artifact relationships require typed FKs plus check/unique/index
  constraints; JSONB holds only bounded snapshots, not identity or relational truth.
- All schema changes use a deterministic Alembic migration. Tests upgrade a clean real PostgreSQL database to head,
  verify constraints and compare `Base.metadata`; do not use SQLite or `create_all()` as migration evidence.
- Stable request fingerprints and database uniqueness are the final race-safe idempotency authority for runs,
  versions, role/ordinal media and drafts.
- Provider calls, object reads and local adapter calls never occur inside a DB transaction. Secrets, object keys,
  signed/provider URLs and raw bodies never enter durable rows or API projections.

## Provider and privacy boundary

- Real model mode requires a validated HTTPS origin/path, no credentials in URLs, no redirects, bounded response size,
  bounded timeout/concurrency/attempts and a server-side key. Fixture mode must not construct any network client.
- Persist only allowlisted provider/model, safe request ID, fingerprints, usage, latency, correction count and typed
  errors. Logs use IDs/stage/status; no evidence body, brand chunk body, prompt, response, key or private path.
- Model/source text is untrusted. The prompt marks it as data, and the renderer always escapes it. The model never
  supplies HTML, CSS, URL or media identifiers.

## HTML/API/frontend boundary

- Backend OpenAPI is the only wire contract. Regenerate checked-in OpenAPI and frontend types through project commands;
  never hand-edit generated output or duplicate backend response types.
- Frontend uses TanStack Query for list/detail/mutation/polling and stops polling on every terminal state. It does not
  persist article/package responses in local storage.
- Do not use `dangerouslySetInnerHTML`. The only rendered HTML is served by the bounded preview endpoint and shown in
  a permissionless sandbox iframe with CSP/no-store/nosniff/no-referrer headers.
- Model/source content rendered outside the iframe remains text. URLs and filenames are validated/mapped at one feature
  boundary. Status and simulation meaning must not rely on color alone.
- No component, schema or generated path may expose publish/send/login/account/AppSecret actions or claim that a local
  draft reached WeChat.

## Minimum verification matrix

- Domain: strict article schema, length, exact claim sets, evidence/brand separation, canonical fingerprints,
  renderer escaping and media-placeholder completeness.
- Provider: MockTransport success/schema correction/malformed/oversized/auth/rate-limit/timeout, identity drift,
  usage and redaction; default tests prove zero egress.
- PostgreSQL: migration/head/parity, XOR and state checks, concurrent enqueue, lease recovery, stage resume, role
  separation, replay and unknown-result non-retry.
- API/storage: 202/Location, typed errors, safe media descriptors, preview headers, safe projections and OpenAPI scan
  proving zero credentials/publishing operations.
- Frontend: generated mapper, explicit live click, fixture path, terminal polling, simulation banner, accessible
  body/cover/iframe and absence of unsafe HTML/publish controls.
- Final gates: focused suites, full backend/frontend checks, Compose config without credentials, fixture local demo,
  optional one-run live smoke, `git diff --check` and sensitive-field scan.
