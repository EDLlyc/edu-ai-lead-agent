# Local implementation result

## Scope completed

- Added the three LaTeX compiler-only report suffixes to `.gitignore`.
- Replaced the two secret-shaped Workbench authenticated-URL literals with runtime-built,
  username-only userinfo fixtures; the rejection contracts are unchanged.
- Added a task-local broad offline artifact builder/validator, single-invocation release operator,
  and Docker/network-free builder plus fake/recovery harnesses under `research/`.
- No remote, SSH, production, registry, provider, WeCom, Docker build/load/tag, commit, or push
  operation was performed while producing or testing these files.

The builder and operator are deliberately separate from the application payload. They bind the c66 baseline,
candidate image ID, dependency base, source archive/manifest/image-source hashes, separate base and
final pyproject hashes, unchanged runtime lock/Dockerfile, exact stage shape, runtime vectors, and
the preserved `.env`/`.release.env` hashes plus observed uid:gid. It validates a root-owned mode-0700
same-device backup/temp root before any stop, supports only bounded `backend/app` candidate source
additions, creates immutable c66 rollback tags, and removes those additions before restoring the
prior source archive. The candidate is pinned and revalidated as `linux/amd64`; the classic image
archive validator binds every layer byte to its ordered config `rootfs.diff_ids` entry.

## Clean-builder handoff contract (implemented, not run against a final release SHA here)

The immutable artifacts must be generated from a clean detached checkout of the fetched Codeup SHA.
The builder must fail unless `git status --porcelain=v1 --untracked-files=all` is empty and
`git rev-parse HEAD` equals the reviewed full candidate SHA. Values below are derived by commands;
none is entered by hand.

1. Generate the c66 path baseline with exactly this pathspec and require exactly 307 sorted paths:

   ```bash
   git ls-tree -r --name-only c66aa6217d137033118c552f3db11b2a1121d082 -- \
     backend deploy infra scripts compose.yaml .env.example .gitattributes .gitignore \
     AGENTS.md Makefile README.md environment.yml | LC_ALL=C sort > previous-paths.list
   test "$(wc -l < previous-paths.list)" -eq 307
   ```

2. Require every previous path at the candidate SHA. Candidate source membership is that exact
   307-path set plus only candidate-only tracked regular `backend/app/**/*.py` or
   `backend/app/**/*.html` files. New `frontend`, `backend/tests`, `backend/evals`, reports,
   `.trellis`, private data, env files, caches, and build output are not runtime-overlay members.
   Produce a sorted NUL list and archive without option interpretation:

   ```bash
   git ls-files -z -- backend/app | \
     while IFS= read -r -d '' path; do case "$path" in *.py|*.html) printf '%s\0' "$path";; esac; done \
     > app-source.list0
   tr '\0' '\n' < app-source.list0 | LC_ALL=C sort -u > app-source.list
   comm -23 previous-paths.list <(git ls-tree -r --name-only HEAD | LC_ALL=C sort) | test ! -s /dev/stdin
   { cat previous-paths.list; comm -13 previous-paths.list app-source.list; } | LC_ALL=C sort -u > candidate-paths.list
   python3 -c 'import pathlib,sys; pathlib.Path(sys.argv[2]).write_bytes(b"".join(p.encode()+b"\0" for p in pathlib.Path(sys.argv[1]).read_text().splitlines()))' \
     candidate-paths.list candidate-paths.list0
   xargs -0 sha256sum < candidate-paths.list0 > source-files.sha256
   tar --null --verbatim-files-from -C "$CLEAN_DETACHED_ROOT" -czf source.tar.gz -T candidate-paths.list0
   ```

   Run `validate-broad-offline-artifacts.py source` with the derived line count. Candidate archive
   regular modes are only 0644/0664 or 0755/0775; directory modes, if emitted, are only 0755/0775.

3. Derive the image-source manifest before building from `backend/alembic.ini`,
   `backend/pyproject.toml`, and sorted `backend/{app,alembic}` `.py`/`.html` files, rewriting the
   leading `backend/` to the image paths under `/app`. The reviewed c66 scope is exactly 165 files
   and the exact 14 Workbench additions produce the required candidate count of 179.

4. Build offline from the clean committed `backend` context and already-verified dependency base.
   Apply these exact labels using derived hashes:

   - `org.opencontainers.image.revision=<full candidate SHA>`
   - `io.trellis.dependency-base.digest=<exact sha256 image ID>`
   - `io.trellis.dependency-input.base-pyproject-sha256=<c66 backend/pyproject.toml sha256>`
   - `io.trellis.dependency-input.final-pyproject-sha256=<candidate backend/pyproject.toml sha256>`
   - `io.trellis.dependency-input.runtime-lock-sha256=<candidate runtime.lock sha256>`
   - `io.trellis.dependency-input.dockerfile-sha256=<candidate Dockerfile sha256>`
   - `io.trellis.release.source-archive-sha256=<source.tar.gz sha256>`
   - `io.trellis.release.source-manifest-sha256=<source-files.sha256 sha256>`
   - `io.trellis.release.image-source-manifest-sha256=<image-source-files.sha256 sha256>`

   Build with explicit `--platform linux/amd64`, export the exact isolated tag with `docker image
   save`, gzip it without a timestamp, and validate its complete classic graph before transfer.
   `image-validation.txt`
   must contain the exact runtime-lock, Dockerfile, base/final pyproject hashes plus
   `production_dependency_delta=none`, `dev_dependency_delta=mcp==2.0.0`,
   `pytest_pythonpath=.`, and `supported_mcp_imports=0`.

5. Copy only the operator's `STAGE_MEMBERS` into a fresh root-owned mode-0700 stage, make every
   member root-owned mode-0600, generate the inner archive checksum files and exact
   `artifacts.sha256`, and derive every invocation hash/count with `sha256sum`/`wc -l`. Capture env
   arguments with `sha256sum` and `stat -c '%u %g'`; do not assume root ownership. Durable/provider/
   source vectors and the safe-until time come only from the reviewed read-only preflight queries.

## Remaining release work

The clean Codeup commit, candidate image, offline image bundle, protected stage, production read-only
preflight, one-shot invocation, and independent production review do not exist yet. This local run
therefore establishes operator behavior only; it is not deployment evidence and must not be used to
claim Phases 2–6 complete.

## Focused independent review

The task-local review fixed three release blockers: explicit `linux/amd64` build/runtime identity,
classic-archive layer-to-`rootfs.diff_ids` validation, and immutable per-service c66 rollback tags.
It also made recovery marker/env restoration return explicitly on every failed prerequisite rather
than depending on shell `errexit`, and bound the production operator to exact 321-source/179-image
counts plus the reviewed 14 additions and 20-line image evidence. The final release contract does
not claim a predictive startup create/claim projection: the application exposes no complete pure
read-only projection API, so a duplicated SQL mirror is deferred. The operator instead requires a
sufficient safe window and zero observed actionable/nonterminal plus legacy-prompt vectors before
the first stop and immediately before each scheduler/dispatcher, starts them sequentially, and
rechecks the same vectors after each start; any post-`.7` creation/drift reaches the existing
stop-all-eight incident disposition.

- Operator SHA-256: `80aa3e2f9f72dc375aeb6884a1d34ed97f4234b1f4cbfdcc9c8e7ee4d0d0aaef`
- Operator harness SHA-256: `3471ab4056b3eac1da40164785161aba21062347fbbae34e955c33aa04670072`
- Validator SHA-256: `183db15c8938e9e235b0529d227ee6c0ed32bbb9460dc40d5bd2a06197e6515b`
- Builder SHA-256: `873080ab8ba20e5073bfbaa327663062ce529c60ccc661bf96ec4a5ae99da7b1`
- Builder harness SHA-256: `b6284cec4a66299b8b2c034a6c8e258e6e93df0e2c34cd6050e1e8cca0614963`

`bash -n`, both focused harnesses, Python compile, Ruff, Mypy, task-context validation,
tracked/untracked diff checks, and the scoped high-confidence secret scan pass. ShellCheck and
gitleaks are unavailable in this environment. No Docker build/load or external action was run.
