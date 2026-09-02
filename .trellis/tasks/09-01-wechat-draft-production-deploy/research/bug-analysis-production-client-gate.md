# Bug Analysis: Production Draft Worker Rejected By Development-Only Client Gate

## 1. Root Cause Category

- **Category**: C - Change Propagation Failure, with a D - Test Coverage Gap.
- **Specific cause**: production acknowledgement was added to `Settings`, Compose, and the worker
  activation path, but `WeChatOfficialAccountHttpClient` retained its former
  `APP_ENV == development` condition. The container therefore passed settings validation and
  entered Docker's running state before adapter construction returned
  `wechat_mp_config_disabled`; `restart: unless-stopped` then created a restart loop.

## 2. Why Earlier Checks Did Not Catch It

1. Settings tests proved that production plus acknowledgement was valid, but did not construct the
   real settings-bound HTTP client.
2. Compose contract tests proved flags, mounts, command, and portlessness, but did not run one idle
   production-shaped worker cycle.
3. The activation check initially observed a running container. The later 30-second stability gate
   correctly detected the restart loop and triggered zero-effect recovery.
4. Recovery removed the failed container before preserving its safe logs. Docker daemon events and
   a bounded `worker --once` diagnostic still established repeated exits and the stable error code,
   but future recovery should capture redacted logs before removal.

## 3. Prevention Mechanisms

| Priority | Mechanism | Specific action | Status |
|---|---|---|---|
| P0 | Architecture | Make the client accept exactly development, or production with the explicit acknowledgement | Done |
| P0 | Contract test | Construct the real HTTP client from acknowledged production settings with a fake transport | Done |
| P0 | Runtime gate | Require restart-zero idle stability, not only the first running observation | Done |
| P1 | Evidence | Capture bounded safe worker logs before recovery removes the container | Planned in the replacement operator |
| P1 | Documentation | Record runtime-consumer gate propagation in the backend and cross-layer specs | Done |

## 4. Systematic Expansion

- **Similar issues**: any feature whose settings predicate is repeated in an adapter, entrypoint,
  dependency factory, Compose health check, or release probe can drift in the same way.
- **Design improvement**: `Settings` owns cross-field validation; downstream checks remain
  defense-in-depth predicates and are exercised by construction tests.
- **Process improvement**: every newly accepted environment must be traced through the real
  process entrypoint and observed for one bounded idle cycle before activation is accepted.

## 5. Knowledge Capture

- [x] Update `.trellis/spec/backend/wechat-official-account-drafts.md`.
- [x] Update `.trellis/spec/guides/cross-layer-thinking-guide.md`.
- [x] Add the production client-construction regression.
- [ ] Bind the fixed commit/image to a new single-use post-migration operator and record its final
      production evidence.

No template-spec directory exists in this repository, so there is no generated spec copy to sync.
