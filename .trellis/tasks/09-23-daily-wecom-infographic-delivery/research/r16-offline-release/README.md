# R16 infographic offline OCI release path — not yet deployed

**Status: code reviewed for a locked preflight; production not changed.** This
directory now contains sealed `r16_release_cli.py` and `r16_enablement.py`
entry points in addition to source/image checks and fake-host tests. Use only
the reviewed `python3 -I` entry points from one root-owned, hash-bound bundle;
the older `r16_forward_operator.py apply` remains intentionally blocked.
Neither a passing local test nor a supplied JSON receipt authorizes a live
`apply` or `enable`: the final commit's full OCI image/bundle, locked live
baseline, fresh backup/clone and real release receipt are still missing.

The first sealed read-only preflight on 2026-09-27 found 19 historical,
non-automatically-claimable rows and stopped at `baseline_identity` without
creating a release attempt. Their exact cohort was reviewed in
`../r16-historical-work-review-20260927.md`. A subsequent candidate adds one
hash-bound exception for those unchanged rows only; the former `c3d5589`
image/bundle cannot be promoted with an operator-only edit. Build a new full
image from the final reviewed commit and repeat the sealed preflight before
any live release action.

The next read-only preflight correctly stopped on two **current** queued
2026-09-27 evening WeCom deliveries whose `not_before` is 18:30 Asia/Shanghai.
They are not part of the historical exception and must complete normally
before another idle release preflight. A further path audit found that the
production `/opt` ancestor is owned by the application Unix user, while the
sealed enablement CLI requires every release-receipt ancestor to be root
owned. The R16 one-attempt backup/receipt root is therefore
`/root/edu-ai-release-backups` (root-owned 0700); the existing backup timer
and its `/opt/edu-ai-release-backups` data are left untouched. A new full
image and bundle are again required after this operator change.

## Frozen starting identity

Read-only inspection on 2026-09-26 found:

| Item | Expected value |
|---|---|
| Protected production commit | `36b24d67b969a433f19c691bb9d12a3c13e00244` |
| Running application image ID | `sha256:d740275be855c258d2dbaccb180b65e8a14e949070f8597fcca4b3fb984eeb1f` |
| R15 OCI archive SHA-256 | `35d37e5aa2eb5a348475c8e9225c0a8a4953b842b4ffed51b582b9d3707a464e` |
| R15 private manifest SHA-256 | `139800ad92c79ecc418e60a38c241f4dc7a1b3f3edbed3119db9e727c878d04b` |
| Live Alembic head | `20260916_0048` |
| Existing application topology | 12 healthy long-running services, no infographic producer |
| Standard digest-release metadata | `.release-manifest.json` absent; do not fabricate it |

The local verified R15 bundle is
`/root/projects/edu-ai-lead-agent/output/moments-r15-36b24d6/`. The read-only
`r16_gate.py` verifies its archive SHA and native OCI graph using the pinned
R15 checker before considering a **committed** descendant. Example after the
candidate has been independently reviewed and committed:

```text
python3 r16_gate.py \
  --repo /root/projects/edu-ai-lead-agent/.trellis/worktrees/wecom-infographic-r15-port.20260926 \
  --revision FULL_40_CHARACTER_CANDIDATE_COMMIT \
  --r15-bundle /root/projects/edu-ai-lead-agent/output/moments-r15-36b24d6
```

A source-gate `passed` result intentionally still says
`deployment_ready=false`. The independently checked candidate was committed as
`192870567c2988f99e36191d956c046043b76577` on 2026-09-26; the read-only
gate passed on that clean HEAD with 77 changed files and explicitly returned
`deployment_ready=false`. This does not satisfy the image, recipient, build,
backup or activation gates below.

The source gate now also refuses a floating font build. A future candidate
must retain the pinned Python base, replace Debian's mutable apt source with
an actually used dated `snapshot.debian.org` source before `apt-get update`,
and install `fonts-noto-cjk` at an explicit Debian package version. This is
only a static source condition: image verification must still prove the
installed package version and font-file hashes. A candidate with an
unversioned `apt-get install fonts-noto-cjk` is deliberately blocked and must
not be represented as a reproducible release.

## Why a new operator and full image are mandatory

The R15 operator is a fixed, one-attempt R14→R15 overlay for a single
`copy_generation.py` change. This candidate adds many application modules,
new `0049` and `0050` migrations, a Compose profile and `fonts-noto-cjk` in
the Dockerfile. An app-only OCI layer over the R15 image would omit the font
package and migration bytes. Reusing the R15 attempt or previous backup path
would be a false release.

Build a **new full runtime image** from an exact reviewed Git commit, not the
dirty checkout. Freeze the resolved base image and font package inputs; the
first R16 candidate pinned the Python base but left the Debian
`fonts-noto-cjk` package floating, so it is not a valid build input. Record
the built image ID, all OCI archive
blobs/config/manifest digests, revision label, `/app/app` and `/app/alembic`
trees, Noto font identity/Pillow Chinese-glyph load and the exact `compose.yaml` and migration
declaration hashes. Verify an offline `docker load` and a network-none,
read-only runtime probe on a non-production host. The host receives the
immutable OCI archive and a separately hash-bound protected-file bundle;
never build or fetch packages on production during activation.

`r16_oci.py` is a **local-only** deterministic Docker-save→OCI packaging and
graph checker. Once a reviewed, clean, committed full image has been built
under the required R16 tag, export it with `docker save -o` into a new private
local directory and run:

```text
python3 r16_oci.py \
  --docker-archive /private/new-r16/docker-image.tar \
  --output /private/new-r16/backend-image.oci.tar.gz \
  --tag offline.local/edu-ai/edu-ai-lead-agent-backend:infographic-r16-COMMIT12 \
  --revision FULL_40_CHARACTER_CANDIDATE_COMMIT
```

The converter checks the Docker revision label, immutable config digest,
every raw layer's `diff_id`, every compressed OCI blob and the complete OCI
index/manifest graph. It refuses to overwrite an existing output. Its JSON
result is **image evidence only**, not an activation manifest, font-runtime
probe, host preflight, backup receipt or permission to copy/apply it remotely.
It accepts both older Docker-save archives with raw tar layers and Docker 29
containerd archives whose `manifest.json` points at gzip blobs; both must
decompress to the declared `rootfs.diff_ids` before deterministic OCI packing.

After recording the converter's `image` and `config_id`, run `r16_smoke.py`
against that exact archive and a clean checkout at the same commit. It loads
the archive locally, then runs the image with `--network none --read-only`,
compares `/app/app` and `/app/alembic` plus config files byte-for-byte against
the commit, imports all runtime entry points including the optional poster
producer, checks Alembic head `0050`, `pip check`, the committed Noto package
version/full font-file SHA and Pillow Chinese-glyph load, and validates Compose with
and without the optional infographic profile. It never starts a business
service or calls a provider. Example:

```text
python3 r16_smoke.py \
  --repo /root/projects/edu-ai-lead-agent/.trellis/worktrees/wecom-infographic-r15-port.20260926 \
  --revision FULL_40_CHARACTER_CANDIDATE_COMMIT \
  --archive /private/new-r16/backend-image.oci.tar.gz \
  --config-id sha256:FROM_CONVERTER \
  --image sha256:FROM_CONVERTER
```

The new production operator must be source-reviewed and independently tested
before it can be bundled. It should use a fresh, root-owned, single-attempt
directory and both existing deployment/backup locks. An existing attempt
directory means reconcile-only, never retry by renaming it. Bind the operator
hash, candidate image digest, committed source tree, host-file hashes,
migration chain and fresh baseline SHA into one signed or independently
reviewed activation record.

## Mandatory capture before *any* production mutation

Under both locks, recapture rather than trust the 2026-09-26 observation:

1. Exact `.release-commit` **and** `RELEASE_COMMIT`, `.release.env` `APP_IMAGE`,
   loaded image ID/labels, all 12 live containers, zero abnormal restarts,
   service commands, mounts, image references and safe environment
   fingerprints. Compare a full runtime tree of the live image with the
   frozen R15 bundle; do not infer it from a tag.
2. Protected files and metadata: `.env`, `.release.env`, both commit markers,
   `compose.yaml`, release scripts/config, Doctor and production-check scripts.
   Store hashes and owner/mode, not secret values in reports. The new Compose
   must preserve existing text/original-image and Official Account settings.
3. Database head `0048`, business/job counts and identity hashes, current
   active/unknown/pending work, scheduled window, active brand pointers,
   character-reference SHA, private brand-material tree, three persistent
   non-PostgreSQL volumes, PostgreSQL/MinIO identities and backup timer.
   Capture all original application services and prove the optional
   infographic producer is absent. Do not start or backfill it at capture.
4. The configured fixed internal group must be checked without displaying
   its webhook key. Bind an opaque recipient fingerprint to the subsequent
   visible-test receipts. A present key alone does not prove recipient
   identity. No send occurs in this capture.
5. Before pausing writers, require a genuinely idle business window and no
   unresolved new `delivery_unknown`/`result_unknown` or queued replay risk.
   Historical immutable exceptions require individually reviewed hashes,
   not blanket status exclusions.

Do not use the current standard `deploy/release/deploy.py` as-is: the standard
manifest/current-state baseline is absent, and its static 12-service phase
table does not describe the optional infographic profile. The R16 operator
must either leave the new producer absent in the default-off activation and
verify that deliberate topology, or supply a separately reviewed phase and
profile; it cannot silently assume a thirteenth existing service.

## Backup, activation and recovery contract

Under both locks, recapture the idle 0048 baseline, write a single-attempt
pause intent, then stop and verify **all application writers**. While they
remain stopped, capture a quiescent baseline and take a *new* PostgreSQL `-Fc`
dump, validating it with `pg_restore -l` and an isolated clone restore.
Inventory/copy all three non-PostgreSQL volumes, private brand assets,
protected host files and source/configuration, with SHA-256, size, metadata
and separate readbacks. Recapture the same quiescent identity after backup.
No backup from live writers is a coherent release backup; the R15 backup is
historical evidence, not a backup of the current 0048 state.

The reviewed migration is `0048 → 0049 → 0050`. Test it against an isolated
clone of the actual production-shaped 0048 schema and verify all existing
table counts/identity hashes survive. `0049` adds five infographic tables;
`0050` adds advisory fields. Both have retained-evidence downgrade fences.
`deploy/release/migration-compatibility.json` declares
`previous_application_compatible=false`: **after a migration attempt, do not
restart the R15 application, restore an old database, downgrade or replay old
jobs.** On any uncertain or partial migration/activation result, stop all
application writers and move to separately reviewed forward recovery. The
backup is for forensic/disaster planning, not automatic rollback.

After the stopped-writer backup is verified, load/verify the exact candidate
image and use it to rehearse the clone against that same dump. Only after the
clone readback passes may an operator write a separate migration intent, run
Alembic once to exactly `0050`, replace
only reviewed protected host files and image markers, then start the existing
12 application services under **all infographic flags false**. The optional
producer remains absent. Verify API health, schema, all service identities,
brand/runtime/protected-file integrity, unchanged historical state, no new
business work and a complete bounded idle cycle. This is *default-off code
deployment*, not automatic poster delivery.

The Compose `wecom-infographic-producer` service depends on `backend-migrate`,
whose command also runs `app.seed_sources` after Alembic; `backend-migrate`
depends on `minio-init`. A direct `docker compose up` of the producer is not a
safe activation command. The drafted default-off restart uses `--no-deps` on
the existing 12 services and neither starts the producer nor requests those
one-shot dependencies. Any later producer start needs a separately reviewed
no-dependency command and fresh recipient/quality gates.

The historical strict plan required a fixed-group same-package triple and
morning gray before expansion; it remains available as a separate policy,
but the user explicitly approved a versioned **direct-first-live all-news**
route. After the real default-off receipt, that route enables all three slots
and ordinals 1–3 together and permits the first passing poster to reach the
existing ordinary group. It is not authorized by the default-off receipt
alone; the explicit decision record and every per-poster hard check remain.
Keep the original text/image and M/W/F Official Account paths unchanged; do not
backfill old news. If any gate fails, leave
infographic delivery/producer off and preserve the existing workflow.

## Forward-only operator contract and sealed CLI

`r16_forward_operator.py plan` validates the *shape* and internal identity of
the candidate manifest, 12-service default-off baseline, and exact image/archive
identity. Three distinct same-package quality receipts and the fixed-group
triple remain **strict-mode enablement** gates checked by
`valid_enablement_evidence`; direct-first-live instead requires its explicit
authorization record and same-news per-poster hard checks. Neither policy is
a prerequisite for the default-off code release. This plan always reports
`enablement_ready=false`. It deliberately rejects
a pre-existing migration-clone receipt: the clone must use this attempt's
fresh stopped-writer dump, whose SHA does not exist at plan time. Its output
always says `production_apply_available=false`: supplied JSON cannot
authenticate live host state or real provider outcomes.
The module's `simulate` function is exercised only with injected fake hosts
and local attempt/lock paths; it is **not a sandbox** and Python cannot prove
that an arbitrary injected adapter has no external side effects. Never import
it with a real host adapter. The CLI exposes no simulation action and `apply`
always refuses. The simulation requires both locks, one fresh running baseline,
a durable pause intent, a verified stop of all writers, then two identical
quiescent captures around a backup receipt that separately accounts for a
readable PostgreSQL dump/TOC, all three volume readbacks, private
brand-material readback, complete source/config archives and exact protected-
file metadata. It then stages the exact candidate image, rehearses isolated
restore and `0048→0049→0050` upgrade from that **same newly captured dump**,
verifies the clone receipt's dump SHA/business identity and writes a separate
migration intent. It migrates once forward, requires a freshly
read exact `0050` head, and installs/starts the original
12 services default-off and verifies them. Any post-intent failure records
`forward-recovery-required` before calling `stop_all`, so even a failed stop
does not erase the recovery warning; an existing attempt is
reconcile-only. The fake-host tests cover success, missing receipts,
duplicate attempts, backup failure, partial stop, ambiguous migration and
post-migration failures. These tests are **not** a production migration,
backup or activation rehearsal.

The simulation checks the freshly returned clone receipt's self-hash and
exact dump SHA before migration intent. A prior receipt, forged receipt SHA,
changed dump bytes or failed restore cannot pass. This is still a fake-host
contract, not proof that any real backup can be restored. `plan` remains
`production_apply_available=false` even when every preflight field is present.

The migration call in this contract is explicitly `python -m alembic -c
/app/alembic.ini upgrade 20260926_0050`; the adapter must **not** invoke
Compose `backend-migrate` (it also seeds sources) or `minio-init`. The clone
rehearsal and production upgrade must preserve existing source/business rows.

`r16_real_host.py` implements the host operations behind the separately
sealed `r16_release_cli.py`; it is not a standalone command.
It computes a live baseline from release markers, image/container inspection,
protected file metadata, stopped-writer business row hashes, brand and named
volume trees; creates a private custom PostgreSQL dump plus TOC readback,
protected/source/config and all three volume/brand archives with per-entry
byte/owner/mode readback; stages an exact archive SHA/image digest; and models
an internal-network, unpublished-port clone using the same dump. Its only
migration command is candidate-image Alembic to `0050`, never
`backend-migrate`, `seed_sources` or `minio-init`. It then has hash-checked
host-file replacement, a 12-service default-off start and identity/health
postcheck. Fake-runner tests exercise those command shapes and local file
copies, including failures. Direct Python imports are **not a security
sandbox**: the only supported operational route is the independently
hash-checked, isolated-Python CLI from a root-owned bundle. Historical
unknown/queued work is fail-closed; any exception requires a specific
independently reviewed cohort hash. The current group's two key hashes prove
the same webhook key, not the membership of that group. A release attempt
with `migration-intent.json` but no success receipt is reconcile-only,
including after a power loss; never rename/retry that attempt.

The release begins with all infographic flags false and the optional producer
absent, preserving original WeCom text/image and Official Account behavior.
This is an **atomic intermediate state**, not the user's requested outcome.
The user explicitly authorized `direct_first_live`: the first successful,
individually checked poster may reach the existing ordinary group without
three preapproved JPEGs or a fixed-test-group triple. Legacy strict mode
retains those gates. Direct mode still requires the exact authorization
record, unchanged existing webhook-key fingerprint, same-package final-JPEG
source/date/URL, byte/geometry and unknown-result checks. Advisory OCR/visual
findings are warnings, never false passes. A provider failure affects only
that news's supplement; original copy/image remain on schedule and no old
poster is substituted.

`r16_enablement.py` and `r16_enable_host.py` now provide a separate sealed
enablement path after a **real** strong default-off release receipt. It
requires schema 0050, 12 healthy original services, the same ordinary group,
the root-owned 0600 authorization record with SHA-256
`ea52cdb7d3c26737e83a13c64893a35b367354ef051e9f3412860790e6def2b2`,
and effective dispatcher/producer settings: producer/delivery=true,
test=false, morning/noon/evening=true, advisory review and
`WECOM_INFOGRAPHIC_MAX_ORDINAL=3`. It restarts only reviewed services with
`--no-deps --no-build --pull never`, forbids `backend-migrate`, `seed_sources`
and `minio-init`, and writes a separate one-attempt receipt after postcheck.
An uncertain prior attempt cannot be renamed and replayed. On failure it
disables only the new supplement path while preserving the base flow.
No fake-host result proves a live release or send.

### Controlled command boundary — no production execution yet

After final commit and full image rebuild, stage exactly one root-owned 0700
bundle containing `candidate.json`, the verified OCI archive, the five R16
operator/adapter source files and the exact reviewed host-file set. All bundle
ancestors must be root-owned and not group/other writable. Use isolated
`python3 -I` and pass independently reviewed full manifest and launcher
hashes; do not rely on ambient `DOCKER_HOST`, shell feature flags or a copied
script outside that bundle. The first invocation may only be `preflight`.
`apply --execute` additionally requires the exact R15 baseline, final image,
recipient and target-schema confirmations, a fresh private attempt directory
and a verified idle window. It must stop all writers before the fresh full
backup and same-dump isolated migration rehearsal. A failed or unknown
attempt is reconcile-only, not retryable by changing the attempt name.

The later `enable --execute` uses the **same sealed bundle**, authenticated
production release attempt/receipt and a private root-owned 0600 copy of
`research/r16-direct-first-live-authorization-20260927.md`. It never
substitutes a test/simulation receipt. The root-level project source file is
the audit record; it is not a secret credential or a cryptographic signature.
No `apply` or `enable` command has been run on production as of this entry.

### Exact local image verification for commit `4312451` (2026-09-27)

A full image was built from clean commit
`43124512385686a2427f1120f343c6697a865092`, with the pinned Python base,
Debian snapshot `20260901T000000Z`, exact `fonts-noto-cjk`
`1:20220127+repack1-1`, downloaded package SHA
`4a2515eb6db3978b897fef9709ed0d2b1f4c6c4df4d83d6c4ef65f71f1b1f502`
and TTC SHA
`b76b0433203017ca80401b2ee0dd69350349871c4b19d504c34dbdd80541690a`
verified during build. The original Docker save is 226,487,808 bytes with
SHA-256 `7ba32147e74173a0f50407f941f96a2e9d15d6a70a185a5a7d7632796ef8669c`.
The 11-layer OCI archive is 222,109,840 bytes with SHA-256
`d7b5e8fd6222de883512cb9e1c8407681ef305463b6be38361f7f7b0dcbdfca4`;
its manifest/image digest is
`sha256:a2936357441f4d86a43dbe10bb0899dd39f1fdf7a5a5cac6bc7a17111c728028`
and config blob digest is
`sha256:1c0b8b6c5734a7a6cd07dc4a4a38f134e016e89e7f43dcb1f9f2c13eb5a49b67`.
Local offline `docker load` returned the same manifest digest. The network-none,
read-only smoke passed 359 exact source files, the optional producer and other
runtime imports, OpenAPI, `pip check`, Alembic head `0050`, the full font SHA,
Pillow Chinese glyphs and both Compose profile shapes. The private artifacts
are under `output/wecom-infographic-r16-431245123856/` in the root workspace.
This is **local image evidence only**. The image source commit `4312451` and a
later reviewed operator-source commit may differ if the two identities are
explicitly bound in a release record and a committed-tree diff proves that
runtime, migrations, Compose and protected host-file bytes did not change.
Otherwise, build a new full image from the later commit. Never relabel the
`4312451` image or claim its revision label names later source bytes.

## Open release evidence — no safe apply yet

- [x] Candidate source is committed; `r16_gate.py` passes on a clean HEAD.
- [x] Local full-image build for source commit `4312451` passed pinned Noto,
      immutable archive graph, runtime tree and offline load/font probes; this
      is not a production load or approval of a later operator-source commit.
- [x] R16 release/enable CLI code paths have independent fake-host review and
      tests for default-off 12-service topology, strict bundle identity,
      one-attempt receipts and fail-forward branches; **no live execution or
      final-bundle attestation has happened**.
- [ ] Final commit's full image and one sealed root-owned bundle pass source,
      OCI graph, offline load, runtime and independent manifest/hash review.
- [ ] Isolated production-shaped 0048→0050 migration, retained-history and
      previous-app incompatibility evidence passes.
- [x] The user explicitly waived three preapproved JPEGs and a fixed-group
      triple **for direct-first-live pre-enable only**; neither is falsely
      recorded as passed. Every actual poster still needs its own hard
      source/recipient/final-byte/unknown-result checks.
- [ ] Lock-captured current ordinary-group key fingerprint matches the pinned
      key and both post-release dispatcher/producer effective environments.
- [ ] Fresh production baseline, verified backup and protected brand/material
      identity are captured immediately before an explicit apply.
- [ ] A real default-off release receipt exists; the separate direct-first-live
      enable attempt verifies it and records effective three-slot/ordinal-3
      runtime state. First actual long-image send outcome is observed, not
      inferred from local tests.

Therefore this preparation does **not** authorize a production write or
declare the infographic deployed. The earlier R15 `forward_activate.py` and
the standard release tool must not be repurposed by changing constants.
