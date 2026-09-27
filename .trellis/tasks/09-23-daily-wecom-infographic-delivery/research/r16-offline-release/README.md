# R16 infographic offline OCI release path — preparation only

**Status: NOT DEPLOYABLE.** This directory contains a read-only committed-source
gate and a release specification. It is not an activation operator or a
substitute for the quality, fixed-recipient, backup or migration reviews. It
must not be copied to the production host and run with an improvised `apply`.

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

Before the first stop/migration intent, take a *new* PostgreSQL `-Fc` dump and
validate it with `pg_restore -l`; inventory/copy all three non-PostgreSQL
volumes, private brand assets, protected host files and source/configuration.
Record SHA-256, size, metadata and a separate verified recovery read. The R15
backup is historical evidence, not a backup of the current 0048 state.

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

Only after successful backup and a final byte-for-byte recapture should an
operator write an activation intent, stop the twelve application writers,
load/verify the candidate image, run Alembic once to exactly `0050`, replace
only reviewed protected host files and image markers, then start the existing
12 application services under **all infographic flags false**. The optional
producer remains absent. Verify API health, schema, all service identities,
brand/runtime/protected-file integrity, unchanged historical state, no new
business work and a complete bounded idle cycle. This is *default-off code
deployment*, not automatic poster delivery.

After that separate release receipt exists, do a new fixed-group visible-test
preflight and observe one same-package triple `text → original image →
infographic` with exact job/artifact/recipient identities and no unknown
outcome. Only then review morning gray (one and three independent packages)
before noon/evening flags. Keep the original text/image and M/W/F Official
Account paths unchanged; do not backfill old news. If any gate fails, leave
infographic delivery/producer off and preserve the existing workflow.

## Open release evidence — no safe apply yet

- [x] Candidate source is committed; `r16_gate.py` passes on a clean HEAD.
- [ ] Full-image build is reproducible, including pinned Noto font package,
      immutable archive graph, runtime tree and offline load/font probe.
- [ ] New independently reviewed activation operator and fail-closed tests
      cover 12-service default-off topology, exact host-file changes, lock
      ownership, one-attempt receipts, idle capture, backup and both
      pre-/post-migration forward-recovery branches.
- [ ] Isolated production-shaped 0048→0050 migration, retained-history and
      previous-app incompatibility evidence passes.
- [ ] Three distinct current-news exact group JPEGs pass copy/claim, OCR,
      visual/phone, source/footer and byte gates; no historical poster reuse.
- [ ] Fixed-group recipient is verified and a test-mode triple receipt has
      confirmed outcomes; unresolved/unknown sends are not replayed.
- [ ] Fresh production baseline, verified backup and protected brand/material
      identity are captured immediately before an explicit apply.

Therefore this preparation does **not** authorize a production write or
declare the infographic deployed. The earlier R15 `forward_activate.py` and
the standard release tool must not be repurposed by changing constants.
