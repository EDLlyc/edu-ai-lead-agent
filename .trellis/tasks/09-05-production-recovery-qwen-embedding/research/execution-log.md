# Recovery execution log

## 2026-09-05, 20:14-20:18 CST

- User approved the final recovery-first plan with `继续`; task activated as `in_progress`.
- At 20:15 CST, no new copy run or delivery existed. Last delivery remains September 2 12:30.
- Full production image digest, OCI revision and both release markers agree with deployed
  commit `5c560da71bcbb61b765d3fe82c742cf2d5e676e1`; all 12 application services use that image.
  Fourteen long-running services are running, all restart counts zero/OOM false; the separate
  completed `minio-init` one-shot is not a failed long-running service.
- Protected environment and markers were fingerprinted without exposing their contents; see
  `recovery-runtime-baseline.json`. Database head remains `20260901_0042`.
- Canonical protected seven-job SHA-256 still matches the previous release:
  `657797a7d4b8d51c8355c07c62343610529fc85753ecb7b489dcd2ef3c5dc74c`.
- Counts before any canary: 479 copy attempts, 191 WeCom attempts, 112 material packages,
  95 delivered jobs and one historic failed delivery.
- Remaining acquisition errors: `cas-research/conflict` (3), `stdaily-tech/conflict` (1).
  Other sources provide candidates; these faults are not silently classified as healthy.
- Clean deployed-source worktree: `/tmp/edu-ai-recovery-release.w7Btpe`, detached at the exact
  production commit. Do not edit or remove while the canary implement/check agents use it.
- Focused copy-worker wiring, Zhipu brand, scheduler, copy-generation and WeCom unit tests passed
  against that clean source (`conda run --name edu-ai pytest ... --no-cov -q`, exit 0).
  These are provider-free regressions, not production-delivery acceptance.
- A Trellis implementer is building a task-local, default-no-call, read-only, no-send canary;
  independent review is required before live execution. This task has not called a provider,
  changed production configuration, written production data, restarted a service or sent news.
- Tonight's 19:30 expiry has passed. No forced late delivery or historical replay is authorized.
  The next natural preparation/target is September 6 06:00/07:30 CST; recheck before acting.

## 20:19-20:22 CST: isolated regression checks

- Exact deployed-source tests passed: 130 focused unit cases, 67 Zhipu/WeCom provider-contract
  cases, and 8 copy/slot-delivery PostgreSQL integration cases. All provider transport tests
  used fakes; none called live models or Enterprise WeChat.
- Initial host integration attempt stopped in fixture setup: local 127.0.0.1:5432 was not
  listening. The existing local PostgreSQL container has no attached network endpoint. This
  is separate from production; its container/config was left unchanged.
- Created temporary internal-only test network `edu-ai-recovery-check-20260905` and task-owned
  PostgreSQL/MinIO containers suffixed `-20260905`; no production access or host port exposure.
- Reran with `CI_PYTHON_IMAGE=edu-ai-lead-agent-ci-python:git-94e05326ca51` and
  `CI_COMPOSE_NETWORK=edu-ai-recovery-check-20260905` through the clean worktree's
  `scripts/ci-python.sh`: all 8 integration cases passed. Test fixtures created and removed
  their own randomized databases/buckets. Main owns final container/network cleanup.
- Production host has approximately 5 GiB available RAM, disk usage 37%, and no failed systemd
  units. A bounded JSON-only recent-log projection returned zero parseable rows; it is not
  evidence that no errors occurred and is not used as an acceptance signal.

## 20:28-20:32 CST: reviewed live no-send canary

- The independently reviewed diagnostic passed its zero-call preflight. It matched the exact
  deployed source, release and configuration; 66 unit and 8 real-PostgreSQL safety cases passed.
- Executed one bounded live invocation in the existing content-worker container by stdin,
  without installing files or changing production configuration. It made exactly one embedding
  request (HTTP 200), then one generation request (HTTP 400), and no audit request.
- Active brand vectors: 57; brand retrieval hits: 6. The generator prompt was 24,238 characters
  against the configured 40,000-character input limit. Embedding/retrieval works, but the copy
  provider rejects the generation request. This is not proof of delivery recovery.
- Current configured text provider/model: Zhipu / `glm-5.2`; generator output cap: 2,048 tokens.
  The shared transport discards provider error bodies, so the observed closed local error
  `provider_request_rejected` does not yet distinguish parameters, permissions or content audit.
- Read-only before/after snapshots match: 479 copy attempts, 191 delivery attempts, 112 packages,
  196 copy runs/jobs and 95 delivered jobs. Last delivery remains September 2 12:30 CST.
  Migration head, target terminal state and protected seven-job fingerprint are unchanged.
  See `canary-before.json`, `canary-live-result.json` and `canary-after.json`.
- Do not automatically repeat this failed canary. A separate fixed, nonprivate, one-chat-call
  parameter probe is being implemented and independently reviewed to capture only an official
  allowlisted numeric business error code. No different provider/model/account is authorized.

### Official documentation checked for the next diagnostic

- [Zhipu error-code contract](https://docs.bigmodel.cn/cn/api/api-code): HTTP 400 alone is
  ambiguous; 1211 means model unavailable by code, 1210/1213/1214/1215 concern parameters,
  1261 concerns prompt length, and 1301 denotes a content-safety rejection.
- [Core parameter contract](https://docs.bigmodel.cn/cn/guide/start/concept-param) and
  [GLM-5.2 model page](https://docs.bigmodel.cn/cn/guide/models/text/glm-5.2) do not establish
  that this model requires thinking enabled. The mutable migration page currently concerns
  GLM-5.3; its forced-thinking rule must not be attributed to GLM-5.2.
- The next probe must never emit provider messages, bodies, request IDs, private prompts or
  credentials. Unknown business codes remain unknown, not a guessed diagnosis.

## 20:36-20:38 CST: parameter control passes; news rejection remains unexplained

- Read-only governance aggregates show 15 `zhipu/glm-5.2` invocations today, all succeeded;
  the latest completion is 17:01:55 CST. This historical evidence is not proof of current copy
  generation but argues against treating the entire text model as unavailable all day.
- The independently reviewed fixed-request script passed 51 isolated offline cases, lint,
  formatting and strict mypy. SHA-256:
  `a31b91d47ca089cbbb123cf930f946a7be98e7746fee37cae8781bc8fd91d291`.
- After fresh runtime/environment gates and its zero-call preflight, main executed exactly one
  fixed nonprivate chat request through the deployed copy client. Same endpoint/key/model and
  copy parameters; HTTP 200, strict `ok: true`, latency 1,510 ms. No model/account fallback.
  See `chat-parameter-preflight.json` and `chat-parameter-live-result.json`.
- Durable production counters and the protected historical cohort remain unchanged; see
  `chat-parameter-after.json`. No service restart, configuration change, package or send occurred.
- This control does not identify the cause of the earlier news-bearing HTTP 400. It supplies no
  reason to change production model parameters or credentials. Main approved preparation of one
  explicit error-observation revision of the original diagnostic: same news input and safety
  gates, but opt-in bounded extraction of official numeric business error codes before the
  transport discards them. This is a new measurement, not an automatic retry of the old script.
  A new independent review and fresh operator gates are mandatory before its single invocation.
  No content rewriting to avoid a provider safety refusal is permitted.

## 20:42-20:44 CST: content-safety refusal identified, not production recovery

- New opt-in error-observation revision independently passed 87 provider-free cases, lint,
  formatting and strict mypy. Its unchanged DB authority retains the prior eight real-PostgreSQL
  safety checks. Reviewed SHA-256:
  `344f404cc46a3a71fdbadd2bd855ed01e1ccfad6c0bb45f1f089946c5582174c`.
- Fresh zero-call preflight, runtime/environment and protected-state gates passed. Exactly one
  instrumented invocation made one embedding request (200, six hits) and one generation request
  (400); no audit. The only captured business code was generation `1301`.
- Zhipu documents 1301 as a content-safety refusal affecting input or generated output. This
  identifies the refusal class, **not** an offending word, evidence item, brand fragment or whether
  input versus generated output triggered it. It is not evidence of expired credentials,
  unavailable embedding, invalid chat parameters, or that all other topics are blocked.
  No additional provider call, prompt rewrite or filter-bypass attempt follows this result.
- At 20:44 CST, read-only scope check found today's nine runs reference nine different events;
  only one corresponds to the observed event. All nine retain their original pre-hotfix
  `review_required/copy_provider_unavailable` terminal state; the last was created at 17:02:04.
  Do not rewrite historic causes to 1301 or claim all nine were content-safety refusals.
- Before/after identities and durable counters match again: 479 copy attempts, 191 delivery
  attempts, 112 packages, 196 copy runs/jobs and 95 delivered jobs. Last delivery remains
  September 2 12:30 CST. Exact release, protected environment, Alembic and frozen cohort unchanged.
- Session live-provider total: two embedding requests and three chat requests across three
  explicitly bounded diagnostic invocations; zero audits, images, packages or sends. The parameter
  control succeeded; both content-bearing observations were rejected. All raw content stayed out
  of reports and no production file/configuration/database/service was changed.
- Recovery acceptance AC2/AC3 remains open. Tonight's old selections stay expired and terminal;
  next normal preparation/target is September 6 06:00/07:30 CST. Content review and actual fresh
  accepted-copy/package/formal-delivery evidence remain necessary. Do not claim a future scheduled
  success, install an unrequested background monitor, or archive this unfinished task.

## Local handoff and cleanup

- Recorded the executable error-observation/privacy contract in backend logging guidelines.
  This is documentation plus task-local diagnostics, not a deployed runtime change. Existing
  unrelated dirty application/configuration/reviewer work remains untouched.
- After all checks finished, verified ownership labels and removed only this task's disposable
  PostgreSQL/MinIO containers and internal network. Removed the clean detached deployed-source
  worktree; its tracked contents are reproducible from the recorded commit. Disposable test data
  was removed; production data, the original local stack and all diagnostic evidence were kept.
- Re-running the documented exact-source tests requires recreating that clean worktree and, for
  PostgreSQL tests, the isolated test services. Do not point those tests at production.
- Task artifacts and the new spec section remain uncommitted. No commit, push, production rollout,
  background-monitor installation or task archive was performed. Task status stays `in_progress`
  because formal recovery and duplicate-delivery acceptance have not been met.
- Final 20:46 CST process check: all 14 project long-running containers are still up;
  PostgreSQL, MinIO and acquisition API report healthy. This is process/dependency health,
  not evidence that unused official-account workflows or end-to-end news delivery succeeded.

## 21:03-21:10 CST: approved follow-up content/handling review

- User approved continuing the content review. This follow-up made zero model/provider calls and
  no production writes, restarts, configuration changes, queue resets or sends.
- Read-only selected-evidence metadata identified two public government source URLs and the
  public event headline. Direct page retrieval was unavailable; a matching official Ministry
  of Foreign Affairs publication was reviewed. Its main subject is diplomatic/economic
  cooperation with secondary education/AI mentions. See `public-content-fit-review.md`.
  This does not identify the precise cause within the combined input or generated output.
- Recorded a safe score projection at 21:07: rank 1, total 0.33723653 below 0.59, no hard veto,
  frontier cohort, education relevance 0, eligibility and threshold bypass true. Exact deployed
  code first allows qualified frontier candidates into the governed broad-tech pool, then applies
  eligible government-source ordering priority. Source priority does not itself grant a new
  threshold bypass. This is existing policy, not a score arithmetic failure.
- Four provider-free synthetic editorial cases reproduced incidental AI mentions admitting a
  generic trade meeting, while direct science education and AI research remain eligible and a
  no-technology trade meeting is out of scope. No changed policy was tested or deployed.
- A Trellis implement-agent exact-source audit confirmed observed initial HTTP 400 is already
  non-retryable, persists only individual failed-job state, and neither creates a package nor
  blocks eligible siblings. Historical factory-unavailable errors remain a separate cause.
  See `provider-refusal-flow-review.md`; no provider/runtime patch is justified for this path.
- The audit identified nonblocking diagnosis/display follow-ups, including an all-failed slot
  being labelled ready. They were documented, not implemented or bundled into production recovery.
- Main asked one asynchronous business-scope question: require a substantive technology/AI/science
  education subject, rather than admitting incidental mentions in general current affairs/trade?
  That policy change remains unapproved; the suggested default is not an answer or authorization.
- Fresh 21:09 counter check matches all protected baselines and the last delivered timestamp is
  still September 2 12:30. All 14 long-running containers remain up; PG/MinIO/API healthy.
  See `content-review-after.json`. AC2/AC3 remain open; no future observation/monitor is installed.

## 21:42 CST onward: approved substantive-topic implementation

- The user explicitly approved the proposed substantive technology/AI/science-education boundary
  with "好的，请你处理". R7/AC6 and execution artifacts now record this decision. The earlier
  review's pending-decision note remains historically accurate, not the current approval state.
- Created clean release worktree `/tmp/edu-ai-substantive-release.F7dHHA` on branch
  `release/substantive-news-scope-20260905` from exact deployed commit
  `5c560da71bcbb61b765d3fe82c742cf2d5e676e1`. No dirty main product changes enter this release.
- Reused the native Trellis implement agent for initial read-only version/input/activation mapping.
  Main owns task/spec records and any subsequent operations; agents have no provider, SSH,
  deployment or production-write authority. No further model call or old refused-input replay
  is planned. Formal recovery acceptance remains open.
- Read-only current-release gate passed again. Content scheduler/worker still explicitly use
  `.11` and `qualified-authoritative-priority-v1`; source/image/protected environment remain
  unchanged. Future activation requires an explicit scoped scoring configuration change.
- Implementation mapping found translated taxonomy labels appended to editorial content.
  Approved .12-only content-bearing projection; preserve historical projection and acquisition
  v3 identity. New immutable editorial/scoring names and scheduler conflicts are recorded in
  design. No historic run replacement or version-forced copy replay is part of the patch.
- Created internal-only disposable test network `edu-ai-substantive-check-20260905`, with
  task-labelled `edu-ai-substantive-postgres-20260905` and `edu-ai-substantive-minio-20260905`.
  Both use temporary in-memory data storage and fixed local-only test credentials; no host ports
  or provider network access. Existing developer stack remains untouched; main owns cleanup.
- Task context validation passes; the known quality-guidelines injection-size warning still
  requires the checker to read the complete file in bounded chunks.
- Preliminary independent release review found the normal deployer expects a different primary
  environment owner/manifest state and cannot transact the one-key scoring change. Archived
  incident scripts are frozen to an older base/ref/allowlist and will not be modified or reused
  unchecked. Assigned a separate native implementer only new task-local `substantive-release/`
  artifacts, reusing the tested offline transaction with exact current-base fences, one-key
  configuration mutation and coherent rollback regressions. Main still owns all live operations.
- A second safe read confirmed the protected `.env` itself contains exactly one unquoted
  `CONTENT_SCORING_VERSION=scoring-v1-preview.11-qualified-authoritative-priority` assignment,
  and one unchanged `CONTENT_SELECTION_PRIORITY_RULE_VERSION=qualified-authoritative-priority-v1`.
  This is not merely a rendered Compose default. No protected contents beyond these two public
  version strings were emitted; the exact primary-environment SHA still matched.
- Independent review requires a zero-new-.12-work rollback fence: unchanged database schema alone
  does not prove old code can interpret future new-policy snapshots. The release must finish
  with a 15-minute margin before the actual earliest producer/preparation cutoff; any later
  rollback needs explicit compatibility review, not deletion or relabeling of valid work.
- Preliminary independent product review found an unshipped false-positive class: a generic
  research/requirement verb near an incidental AI mention could label an entire long trade
  sentence substantive. It also found a genuine-science false negative when later measurement
  sentences omit the topic keyword. These are blocking pre-release boundary cases, sent back
  to the implementer for rule-level fixes and regression coverage. No candidate has been deployed.

## 22:28 CST continuation: transient workspace loss

- On the user's "继续", only the main repository/task files remained. The `/tmp` release
  worktree, disposable test services, tool sessions and native agents were no longer available.
  The release branch still pointed to deployed base 5c and its surviving index contained no staged
  changes. Do not interpret interrupted test/build processes as completed or passing.
- Trellis local session search returned no matching transcript. Prior conversation output and
  retained task artifacts preserve the policy/version/integration decisions and reviewer findings;
  the uncommitted product patch must be restored and reverified. Four partial release-tool scripts
  survived under task research; they remain unfinished and not authorized for execution.
- Removed only the stale Git worktree registration for the absent temporary path. Created a new
  clean worktree at `.trellis/worktrees/substantive-news-scope` on the same release branch; local
  Git exclude prevents staging the nested worktree. This path is inside the persistent workspace.
- Before interruption, the old CI image stopped full unit collection because MCP was missing.
  A locked toolchain build and isolated host all-unit diagnostic had started, but their final
  outcomes were not observed. Both must be rerun if needed; no tests are waived.
- No production release, config switch, model call, job replay or news send was made by this
  implementation attempt. Recovery AC2/AC3 remain open.
- Restored only the task-labelled disposable PostgreSQL/MinIO services on their internal network;
  existing developer services were not changed. Host Conda includes MCP 2.0.0; project-default
  Conda checks run with a clean environment and a disconnected network namespace, without
  dependency changes or model access. Focused database checks use the isolated task services.
- Full unit diagnostics completed. A separate exact-5c worktree reproduced the same 31 failure
  IDs (ignored private/demo assets and existing runtime/test-version drift), recorded in
  `substantive-baseline-unit-failures.json`. Do not claim a green full suite or silently fix
  unrelated IP-asset/demo code. Final candidate must introduce no new failures and pass the
  focused changed-scope gates.
- Restored-rule independent review now has a durable 20-case input matrix, not human labels.
  The initial 19/20 result exposed one dedicated-AI-governance false negative for correction.
  Additional review covers predicate/topic-word overlap, bounded normalization and actual
  newline-separated governed fact projections. No production rollout has occurred.
- Fresh independent historical verification passed six config snapshots/roundtrips/fingerprints,
  1,080 score/explanation combinations, twelve v2/v3 outputs and eleven source identities.
  See `substantive-historical-replay-check.json`; a durable provider-free probe is retained.

## 2026-09-06 09:52-09:55 CST: natural production recovery observed

- Read-only production inspection found the unchanged `5c560da7` release and all 14 long-running
  services up. PostgreSQL, MinIO and acquisition API remained healthy; production still pinned
  scoring `.11`. The new substantive `.12` policy had not been deployed.
- The natural morning run created three independent accepted copy runs between 06:02 and 06:05.
  Each had a material package with deterministic validation passed and copy audit accepted.
  Three formal delivery jobs then completed with both text and image delivered at 07:30:01,
  07:31:03 and 07:32:05 CST. Safe lineage is recorded in
  `production-recovery-observation-2026-09-06.json`.
- Each delivery has a distinct copy run, package, delivery job and content-slot selection, with
  sequence ordinals 1, 2 and 3. No duplicate `(content_slot_selection_id, sequence_ordinal)` group
  exists. At 09:55 there were still exactly three delivery jobs for today's slot, zero running
  copy jobs and zero pending/partial/unknown delivery jobs.
- Content scheduler and WeCom dispatcher both poll every two seconds. More than two hours of
  ordinary repeat passes after the final send created no fourth job or duplicate, satisfying AC3
  without a manual replay. The frozen seven historical queued jobs retain exact SHA-256
  `657797a7d4b8d51c8355c07c62343610529fc85753ecb7b489dcd2ef3c5dc74c`.
- These observations satisfy recovery AC2 and AC3. They do not prove or activate `.12`, Qwen,
  official-account publication, or any new provider behavior. The independent `.12` code/release
  check continues separately before a scoped commit or deployment decision.
