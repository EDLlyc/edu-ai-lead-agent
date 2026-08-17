# Result — 部署图片供应商格式容错修复

## Current disposition

The application fix is committed, pushed to Codeup and active in production. Production runs exact
commit `cbc27b2491e4ebd49e6cc58692b065268e2887db` and image
`sha256:b9410598a50417b236eaa68ab1f5660c756269f0cbf258c429c95aaf7f5e7d31` across all
eight application services. The first authorized invocation failed and recovered as recorded
below; the user then explicitly authorized one `retry2` invocation, which completed successfully.

## Codeup and offline candidate

- Application release: `cbc27b2491e4ebd49e6cc58692b065268e2887db`.
- Codeup authority used for the successful build: `35b5e38c29f8e813c48e881bb20ee18a522a8808`.
- Candidate image: `sha256:b9410598a50417b236eaa68ab1f5660c756269f0cbf258c429c95aaf7f5e7d31`.
- Source archive: `00391b955991e8a018089a71a23b70283cf52c9f6fd987c83825d8be3c957344`.
- Source manifest: `b299e309a8535d3e60c9c1a885fd4f74203b6d04a7526c18175b3a299ce9c2f2`
  over exact 321 paths.
- Image-source manifest: `ac58701a6e353b88336e694ced7c9119d225220fcf341bbd040195d00de297d7`
  over exact 179 paths.
- Image bundle: `46bb77783e6fceed11b8d7b81dd280e94525458d7d907df54e35cf9825331918`.
- Previous 7ba source manifest:
  `a1b5d31e9e94e53ab1fa3ec65f5db8b71a1402423d81b59ecf8e54d5febf2fd1`, exact 321 paths.

The clean detached build, source/image graph validators, non-root/network-none/read-only runtime
probes, imports, `pip check`, OpenAPI, Alembic head, scoring and explicit side-effect-free image
feature settings all passed. The first two local builds stopped before artifact acceptance because
the builder probe asserted production-enabled image flags without supplying their environment;
the corrected builder explicitly used `IMAGE_ENABLED=true`, `IMAGE_PROVIDER_MODE=fake`, OCR and
diversity true. The successful stage was then independently checksum- and graph-validated locally
and remotely.

## Production attempt and recovery

The 16-second preflight samples were byte-equal:

- durable: `40:40:13:8:64:40:40:430:25:49`;
- provider: `430:40:49:25:49`;
- sources: `10:38:10`;
- actionable/nonterminal: `0:0:0:0:0:0:0`;
- legacy prompt: `0:0:0`.

All eight application services were exact 7ba/running/restart-zero, scoring remained `.7`, OCR and
diversity were true, and the evening slot had naturally completed with zero selections and no
delivery job. A first protected upload was rejected before root-stage promotion because the prior
and candidate manifests shared a basename; the incomplete unprivileged upload was removed and a
second transfer used distinct targets. A direct execution attempt returned 126 before the operator
entrypoint because the protected operator is mode 0600; the actual unique invocation correctly used
`/bin/bash /absolute/operator` with local and remote stdin `/dev/null`.

The unique operator invocation completed the preflight, isolated image load, quiesce, fresh backup,
candidate retag/source overlay and Alembic-only no-op. It then failed at the post-migration candidate
Settings probe with `AssertionError`. State at failure was `backup_ready=1`, `tags_changed=1`, and
`overlay_changed=1`. Automatic recovery stopped all eight application services, restored the exact
7ba tags/source/markers/services, passed its recovery gate, and exited 1. Fresh backup:
`20260817T100714Z-image-fallback`; protected checksum manifest SHA-256:
`00f1d6779dbe3af1e3d8c836656e842125601c51e925865b7345bb7efcea9eaa`.

Independent recovery samples at `10:09:41Z` and `10:09:58Z` were identical to the preflight vectors.
All eight services were exact 7ba/running/restart-zero, the candidate had zero running containers,
the previous 321-file source manifest passed, env/release-env hashes were unchanged, and the fresh
backup protected checksums passed. Release-caused model, image, provider, WeCom and business deltas
were all zero. No fixture, provider call, enqueue, replay, retry, resend or WeCom send was invoked.

## Root cause and prevention

This is a change-propagation/test-coverage bug, not an application or provider failure. The
production operator retained the same stale probe that had already been corrected in the builder:
it set only `CONTENT_SCORING_VERSION`, constructed `Settings()`, then asserted OCR/diversity true.
Those fields safely default to false and are enabled by production `.env`, so the assertion was
guaranteed to fail. An isolated candidate reproduction returned rc 1 for the old probe and passed
when supplied explicit non-secret, network-disabled settings:
`IMAGE_ENABLED=true`, `IMAGE_PROVIDER_MODE=fake`, `IMAGE_OCR_ENABLED=true`, and
`IMAGE_DIVERSITY_ENABLED=true`.

The operator now uses that exact explicit probe contract. Its harness binds the complete ordered
Docker argv and assertion payload, rather than checking only that phase recovery succeeds. The
backend release quality spec now requires every non-default Settings assertion to supply explicit
allowlisted values and requires builder/operator parity coverage. There is no repository template
copy of this project-specific backend spec to synchronize.

Corrected tooling hashes:

- retry2 operator: `608d132d3dc1f41dfb988776c2f78fdf507662911f80e3ed58990a054a7edf67`;
- operator harness: `4ad70dd46bc2775ad4ced944130af89496c6ac16dab694e3e852de6235b332ec`;
- builder: `5c56137a5fb0d16db8db38ff4185b367e1f7896d4af7af25a102c01407ae573d`;
- builder harness: `771d850acdc1319c4aa2fd2a98512b2c439c37cd28c41ddc0325b617fbfaee97`;
- validator: `0402dc9034711c087f9d50f4ffb4d27ede11a992150efd4090b2a63a937efacc`.

## Successful retry2 activation

The user explicitly authorized a second and final invocation and allowed the current day's business
services to be stopped. At `10:18:27Z`, the fresh retry preflight still showed the exact protected
vectors above and zero actionable/nonterminal work, so no queued work needed to be cancelled or
discarded. The prior invocation marker was retained; the committed retry operator used a distinct
hard-coded `retry2` guard. Codeup authority for this operator was
`b5cfaf4135f306b5c0760ad82e2dc25bacddf770`.

To minimize delay and transfer risk, the new protected stage reused the eight byte-identical,
already remotely validated image/source/validator artifacts. Only the corrected operator and new
aggregate checksum manifest were transferred. The resulting exact ten-member stage passed hashes,
mode/owner, Bash syntax and artifact checks. Aggregate stage manifest SHA-256:
`5a6d1304203026945140697e536aaedc3b69d98bcdc7fca42acb1047eaa0c089`.

The retry operator passed the previously failing candidate Settings probe, completed Alembic-only
no-op migration, restored API first and dispatcher last, and passed its 30-second acceptance gate.
It exited 0 with no fixture, provider or WeCom action. Fresh successful backup:
`20260817T101955Z-image-fallback`; protected checksum manifest SHA-256:
`dcece0a1158198fd647db24deada241cdd084a4d56f65045314ebeb596b21d20`.

Independent post-release samples at `10:22:32Z` and `10:22:48Z` were identical:

- durable: `40:40:13:8:64:40:40:430:25:49`;
- provider: `430:40:49:25:49`;
- sources: `10:38:10`;
- actionable/nonterminal: `0:0:0:0:0:0:0`.

All eight services use the exact cbc candidate image, are running with restart count zero, and no
container runs the prior image. Candidate source/markers and all nine active tags are exact; API,
PostgreSQL and MinIO are healthy; Alembic remains `20260815_0021`; scoring remains `.7`; image
provider remains Comfly; OCR/diversity remain true; production OpenAPI still exposes no Agent
Workbench route. Primary and release env hashes are unchanged. Release-caused model, image,
provider, WeCom and business deltas are zero.
