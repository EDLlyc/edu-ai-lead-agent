# Exact offline artifact and activation recipe

This recipe is frozen to application commit
`cbc27b2491e4ebd49e6cc58692b065268e2887db`, production baseline
`7ba25d3eeb290d3f784ae449a5b6ad360a8def58`, and previous image
`sha256:7627186cf1650a63bbe2e5e136e2364970a9383f756a62ed7db8c6e5cb50b21c`.
It does not authorize a push, artifact build/load, transfer, SSH connection, or production action.

## Local gates after the tooling commit is on Codeup

Run from a clean local `main` after an explicit fetch. The authority SHA may be newer than the
application SHA, but it must be exact Codeup `origin/main` and contain the application commit.

```bash
authority_sha=$(git rev-parse --verify refs/remotes/origin/main^{commit})
test "$(git rev-parse --verify HEAD)" = "$authority_sha"
test -z "$(git status --porcelain=v1 --untracked-files=all)"
git merge-base --is-ancestor \
  cbc27b2491e4ebd49e6cc58692b065268e2887db "$authority_sha"

test_root=$(mktemp -d /tmp/edu-ai-image-fallback-tests.XXXXXX)
candidate_worktree="$test_root/cbc27b2"
git worktree add --detach "$candidate_worktree" \
  cbc27b2491e4ebd49e6cc58692b065268e2887db
(
  cd "$candidate_worktree"
  conda run --name edu-ai pytest \
    backend/tests/unit/test_image_generation.py \
    backend/tests/unit/test_image_fallback.py \
    backend/tests/unit/test_material_package.py \
    backend/tests/unit/test_wecom_delivery.py -q
)
git worktree remove "$candidate_worktree"

bash .trellis/tasks/08-17-deploy-image-output-fallback/research/build-image-fallback-offline-artifacts.sh \
  --authority-sha "$authority_sha" \
  --release-sha cbc27b2491e4ebd49e6cc58692b065268e2887db \
  --output-dir /absolute/new/protected/artifact-directory
```

The builder creates its own clean detached application worktree at exact `cbc27b2`; no caller
worktree byte enters the source or image. It performs no fetch, pull, push, registry operation,
SSH, transfer, or deployment. The build is `linux/amd64`, `--network none`, `--pull=false`, and
uses the immutable dependency base
`sha256:50fd2519fbc5aa204c45e76cb685d01aaea1656b998d3ed96c9ab6671b3b9374`.

The exact 321-file transport/source set has seven expected Git blob changes: the three application
modules plus their four focused unit-test files. The exact 179-file image/runtime set has only the
three reviewed application blob changes. This distinction is deliberate; neither set may gain,
lose, or change any other path or hash.

## Protected stage and one-shot operator

The output directory must stay mode `0700`, with exactly ten mode-`0600` regular files. Verify
`artifacts.sha256`, both bundle sidecars, the printed image ID, and the operator/validator hashes
before transfer. The remote stage must be a new physical root-owned directory matching
`/var/tmp/edu-ai-image-fallback-release-*`.

The production operator is invoked exactly once, by absolute path, from
`/opt/edu-ai-lead-agent`, with stdin from `/dev/null`. Its arguments bind:

- the printed candidate image/tag and four artifact hashes;
- operator and validator hashes;
- the fresh exact 321-line 7ba production source manifest and its hash;
- exact `321` previous/candidate and `179` image-source counts;
- the immutable dependency base ID;
- fresh durable/provider/source vectors and byte-exact env hashes/owners;
- a fresh safe-window deadline.

The operator itself revalidates the protected stage, candidate provenance/runtime, exact seven
source deltas and three runtime deltas, current 7ba image/markers/tags/services, `.7` scoring,
OCR/diversity `true:true`, zero work/provider/WeCom state, and the safe window before the first
stop. It then claims its persistent once-guard and acquires the backup lock before quiescing all
eight services.

No `minio-init`, seed, fixture, replay, enqueue, provider request, WeCom send, configuration
transition, or paid live smoke is part of this recipe. Migration is the explicit Alembic-only
`upgrade head` command and must remain a no-op at `20260815_0021`. Services are recreated one at a
time with `--no-build --no-deps`, API first and dispatcher last.

Do not rerun the operator after any nonzero exit. It performs one phase-aware recovery. Recovery
first stops all eight application writers; if protected or stable-zero vectors drift, it leaves
all writers stopped and reports an incident. Otherwise it restores the exact 7ba source, markers,
shared/service tags, and services with dispatcher last. PostgreSQL and MinIO are evidence-only and
are never automatically restored.
