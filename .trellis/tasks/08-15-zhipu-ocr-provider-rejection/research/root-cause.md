# Root-cause evidence

## Repository and production evidence

- `backend/app/infrastructure/ai/factory.py::_create_image_validation_provider` passes
  `settings.ai_chat_model` into the image OCR adapter.
- `backend/app/infrastructure/ai/image_validation.py` posts an `image_url` content part to
  `{AI_PLATFORM_BASE_URL}/chat/completions`.
- A bounded production Settings probe on 2026-08-15 returned provider `zhipu`, chat model
  `glm-5.2`, base host `open.bigmodel.cn`, base path `/api/paas/v4`, and both production image
  flags false. No secret was read or printed.
- The archived acceptance result records one successful 1024×1024 media validation followed by
  one `provider_request_rejected` OCR terminal, with no stored image or retry.

## Official provider evidence

- [GLM-5.2](https://docs.bigmodel.cn/cn/guide/models/text/glm-5.2) lists input modality as text and
  output modality as text.
- [GLM-5V-Turbo](https://docs.bigmodel.cn/cn/guide/models/vlm/glm-5v-turbo) documents
  `/chat/completions` with `image_url`, including Base64 image input.
- [GLM-OCR](https://docs.bigmodel.cn/cn/guide/models/vlm/glm-ocr) is the provider's dedicated OCR
  model and supports PDF/JPG/PNG.
- [Document parsing API](https://docs.bigmodel.cn/api-reference/%E6%A8%A1%E5%9E%8B-api/%E6%96%87%E6%A1%A3%E8%A7%A3%E6%9E%90)
  fixes the model to `glm-ocr`, accepts URL or Base64, caps a single image at 10 MB, and returns
  bounded `layout_details` with element index, label, normalized `bbox_2d`, and content.

## Root-cause conclusion

The rejection is explained by a deterministic capability mismatch, not by OCR text quality:
the application sent a multimodal `image_url` request to the text-only `glm-5.2` model. The
smallest provider-aligned fix is a separate image OCR model/adapter using `glm-ocr` and
`/layout_parsing`; text generation remains on GLM-5.2.

## Second iteration after the one-call live fixture

The first bounded fixture used the corrected `glm-ocr` capability and reached one HTTP provider
attempt, but the adapter returned `invalid_provider_output`. No raw response body was captured, so
the diagnosis is based only on official contract evidence and the deployed parser's deterministic
schema:

- The official document-parsing response defines `layout_details` as `object[][]`: outer pages,
  then elements. The deployed `_ImageOcrResponse` expected a flat element list.
- Official `data_info.num_pages` is an integer, while `data_info.pages` is an array of page objects
  with positive `width` and `height`. The deployed page-count helper treated `pages` as another
  integer alias and rejected the documented array.
- Official layout elements include page `height` and `width`; the deployed element model used
  `extra="forbid"` without those fields, making the documented example invalid locally.
- Official `image` elements may carry bounded content such as an image reference. The deployed
  projection rejected any non-empty non-text content even though it was neither projected nor
  needed for the exact-text gate.

These are sufficient independent offline causes for the observed generic terminal. The corrected
boundary must accept only one nested page, type and cross-check page metadata/dimensions, ignore
bounded `image` content, reject `table`/`formula`, and retain the exact ordered text gate. Stable,
content-free parsing-stage issue codes are added so a future bounded gate can distinguish envelope,
page-metadata, layout, and unsupported-structure failures without exposing provider data.

## Third offline iteration after the second one-call fixture

The nested-envelope correction reached the raw response parser, but the second bounded fixture
again failed closed with only `image_ocr_layout_invalid`. No raw response or recognized content was
captured. That single broad code is equally predicted by several incompatible hypotheses, so it
does not identify which representation the provider returned.

Pinned official BigModel and `zai-org/GLM-OCR` sources add the following discriminating evidence:

- Raw `index` is an integer with no published minimum/base/continuity invariant. Official SDK
  examples, formatter output, MaaS mocks, and converter paths use or preserve index `0`, while the
  API example uses `1`. Requiring positive one-origin indices was an implicit assumption.
- The API prose describes raw `bbox_2d` in `[0,1]`, while the official MaaS converter and its unit
  tests consume raw pixel coordinates and divide x/y by `data_info.pages` width/height. Requiring
  unit coordinates rejected an officially executable raw path.
- Raw `bbox_2d`, `content`, `height`, and `width` are independently optional in the official schema
  and Python response types. Requiring bbox/content for ignored images or paired element dimensions
  was stricter than the provider contract.
- Raw MaaS labels remain the explicit four-value vocabulary `text/image/table/formula`. The richer
  SDK `json_result` vocabulary is not accepted by this direct HTTP adapter, and normalized SDK
  output is not auto-detected from coordinate magnitude.

### Bayesian update

These values describe confidence in the offline compatibility propositions, not a claim about the
private body returned by the second live call:

| Proposition | Posterior | Discriminator |
| --- | ---: | --- |
| Raw nested pages and exactly one image page are required | 99.5% | OpenAPI, SDK converter, and examples agree |
| Raw MaaS can emit page-bounded pixel boxes | 82% | Official converter formula and full-page pixel unit test; API prose conflicts |
| Raw MaaS can emit documented `[0,1]` boxes | 15% | Explicit API prose; executable examples favor pixels |
| Raw index must accept both zero- and one-origin values | 99% | No schema minimum plus official examples for both |
| Raw fields are independently optional | 98% | OpenAPI required set and official SDK response types |
| The second live failure was specifically bbox scale | Undetermined | Broad prior code has no likelihood-ratio value among parser hypotheses |

The safe correction therefore accepts only the union of two officially supported raw bbox forms:
unit coordinates, or pixels with deterministic positive page axes and range checks. It accepts
bounded unique nonnegative indices without continuity, retains the four-label raw mapping, ignores
image-only and outer extension values without projection, rejects unknown element semantics, and
never guesses an unbound scale. Scale is selected once for the entire text page so a tiny pixel
bbox at or below one cannot be mixed with ordinary pixel boxes and change geometric order. This is
a metadata compatibility change; exact visible three-line acceptance is unchanged.

## Break-loop analysis

### 1. Root-cause categories

- **B — Cross-layer contract:** the private raw HTTP boundary was modeled from one documentation
  example while the provider's official executable converter implemented another coordinate form.
- **D — Test coverage gap:** local fixtures mirrored one-based unit-bbox assumptions rather than
  including official SDK zero-index/pixel fixtures.
- **E — Implicit assumption:** index base, mandatory bbox, paired dimensions, and element/page
  equality were treated as invariants without a versioned provider guarantee.

### 2. Why prior fixes did not close the loop

1. Capability routing fixed the original 400/422 rejection but could not validate the successful
   response representation.
2. The nested-envelope correction fixed four real schema mismatches but retained narrower index,
   bbox, optional-field, and dimension assumptions.
3. Broad parser-stage codes protected privacy but collapsed every remaining hypothesis, so the
   second paid observation could not discriminate a next fix.

### 3. Prevention mechanisms

| Priority | Mechanism | Specific action | Status |
| --- | --- | --- | --- |
| P0 | Architecture | Keep raw MaaS and future SDK-normalized decoders as explicit boundaries; never scale-detect an envelope | Done for raw boundary |
| P0 | Test coverage | Pin normalized-doc and executable pixel fixtures, zero/one index origins, optional fields, and every granular parser code | Done |
| P0 | Runtime safety | Make every parser code terminal before repair/similarity/storage and retain default-off live gates | Done |
| P0 | Parser discrimination | Choose raw bbox scale once per page; reject unknown element keys and raw/normalized/error source conflicts with content-free codes | Done in independent review |
| P1 | Documentation | Record source hierarchy, coordinate conflict, privacy treatment, and exact-gate invariants in the backend spec | Done |
| P1 | Review | Require primary-source executable examples when provider prose and generated types disagree | Required by spec |

The implementation intentionally does not retry the provider, infer the second response body, add
SDK fallback, widen the raw label enum, or change public API/database contracts.

## Offline release archive break-loop

The default-off retry later failed before `docker image load` because the operator driver assumed
every Docker save archive used the classic layout and therefore required
`Config=<candidate-image-id-without-sha256>.json`. The exact protected bundle instead uses the
containerd/OCI layout: its one `index.json` manifest descriptor is
`sha256:03a988512f5f0792ec221be15c83db2ee64972f0fb5c4456eccc0562a8f184a2`, while the referenced
config blob is independently
`sha256:695d4b23d5cfa5a09ac156f9308b23d3e7615b342a00aad19c619bc62f30db0a`. The former is the
candidate image identity; the latter is not. This was reproduced locally by reading the archive
metadata only, with no load, service or provider action.

### Categories and why the prior gate missed it

- **E — Implicit assumption:** image identity was treated as synonymous with the config digest and
  classic config filename. Archive format and the identity-bearing descriptor were never made an
  explicit branch of the contract.
- **D — Test coverage gap:** the bundle-phase mock contained only a classic-style `manifest.json`
  and fabricated config filename. It did not model a real OCI index/manifest/config/layer graph or
  run the validator against the exact engine-produced artifact.

### Prevention

The pre-load gate now distinguishes OCI only through the simultaneous `oci-layout` and
`index.json` markers and otherwise validates the explicitly supported classic form. OCI validation
binds the expected candidate ID to the sole index manifest descriptor, then checks descriptor
media types, sizes, blob hashes, the exact containerd/ref-name annotations against the RepoTag,
the reviewed `linux/amd64` config and its `rootfs.diff_ids` against every ordered raw/gzip layer,
exact `manifest.json` references,
and an exact safe regular-member set. Ambiguous markers, extra images, dangling blobs,
conflicts, traversal, duplicates and non-regular members fail before tag arming or load. The fake
harness now uses the two exact annotation keys emitted by the real containerd archive and includes
realistic OCI and classic positives, the candidate-vs-config regression, strict JSON/schema/media
cases, and independent descriptor/config/layer hash/size/diff-id plus tag/index/manifest/member
negatives. The exact candidate bundle must also pass validator-only before any future execution
review.

## Post-load image source-manifest break-loop

The next authorized retry passed OCI validation and loaded the inactive candidate, then failed the
post-load source-manifest gate. The frozen `image-source-files.sha256` contains 165 exact entries:
root `alembic.ini`, root `pyproject.toml`, and 163 `*.py`/`*.html` files below `app/` and
`alembic/`. The runtime collection command searched only those two directories, so it deterministically
produced 163 entries and omitted both root files. Read-only local comparison proved those were the
only differences; both files exist in the exact candidate and their bytes match the frozen hashes.

### Categories and prevention

- **E — Implicit assumption:** the manifest scope was encoded indirectly as the arguments to one
  `find` command. Nothing made the two root inputs or the complete 165-path domain explicit.
- **D — Test coverage gap:** the bundle-phase fake replaced `assert_candidate_image` with a no-op,
  so the post-load source collection and manifest comparison never executed in the harness.

The driver now separates pure manifest validation from its read-only candidate collection. It
explicitly emits the two non-symlink root files plus the bounded `app/`/`alembic/` source scan,
exports `LC_ALL=C`, NUL-sorts names and uses empty-safe NUL-delimited hashing, and requires the
observed and frozen manifests to be safe,
unique, deterministically ordered, exactly 165 entries and byte-for-byte path/hash equal. The
harness executes the real collection boundary with a fake Docker response whose exact argument
checks explicitly return failure, rather than relying on `errexit` inside a conditional function.
It proves the old 163 form fails through that boundary, 165 passes, and missing root, root hash
drift, extra/replaced path, unsafe filename/hash/order and duplicate cases fail. The transient
observed manifest is registered for EXIT/signal cleanup. A local exact-image smoke repeats both the
correct positive and old-command 163 rejection with network disabled, read-only rootfs, all
capabilities dropped and no image load.

## Post-load entrypoint import break-loop

The following authorized retry passed archive and 165-file gates, then failed before overlay with
`ModuleNotFoundError` for `app.acquisition_scheduler_main`. Compose and the repository define the
acquisition scheduler as `python -m app.scheduler_main`; the exact candidate contains only
`app/scheduler_main.py`. The other current long-lived modules are `app.worker_main`,
`app.governance_scheduler_main`, `app.governance_worker_main`, `app.content_scheduler_main`,
`app.content_worker_main` and `app.wecom_dispatcher_main`, with API target `app.api_main:app`.

### Categories and prevention

- **C — Change propagation:** the Compose service entrypoint contract was not propagated into the
  independently written release import probe.
- **D — Test coverage gap:** bundle arming still replaced the complete `assert_candidate_image`
  gate with a no-op, and the prior local smoke stopped after the manifest sub-gate.
- **E — Implicit assumption:** the probe invented a service-prefixed Python name rather than
  deriving it from the executable module. The same full smoke exposed a second handwritten-name
  assumption in a nonexistent Alembic filename even though revision `20260815_0021` was valid.

The driver now owns one API module constant and one ordered seven-module long-lived entrypoint
array; the import gate passes those values to `importlib`, verifies exact imported names and calls
`openapi()` on the API module's `app` object. The harness derives all eight Compose `*app-runtime`
services, binds them to `APP_SERVICES` and the entrypoint constants, rejects the stale acquisition
module, and drives the complete candidate gate with fake image/label/run outputs whose assertions
return nonzero explicitly rather than relying on suppressed `errexit`. Alembic validation consumes
the head constant, requires exactly one matching revision declaration and requires `alembic heads`
to be exactly one expected line, so an extra head fails without filename coupling. Finally, the
exact inactive candidate passes
the whole network-none/read-only/cap-drop/no-new-privileges gate—identity and labels, 165-file
manifest, all imports, non-root/default-off Settings, `pip check`, OCR route construction,
shadowing, OpenAPI and Alembic—without image load or external access.

## Source archive mode break-loop

The next authorized retry passed the full candidate gate, armed active tags and began the host
overlay, then failed on the first sorted source member. The exact 307-file source archive contains
295 regular files with mode 0664 and 12 with mode 0775; `.env.example` is the first 0664 member.
All frozen paths and content hashes remain exact. The modes came from the group-writable workspace
used to create the archive, while the driver accepted only already-canonical modes. Recovery from
the retained `20260816T064939Z-zhipu-ocr-default-off` rollback restored the prior overlay, tags and
services; no marker, one-shot, migration, candidate service or provider action occurred.

### Categories and prevention

- **E — Implicit environment assumption:** the artifact inherited the builder host's umask and
  group-write bits, but the release process treated those incidental source modes as an intentional
  installation policy.
- **D — Test coverage gap:** synthetic source archives used only canonical 0644/0755 files, so the
  harness never exercised the production-real 0664/0775 artifact or proved that overlay strips
  group-write bits.

Artifact builders should normalize every regular source member to 0644 or 0755 before hashing and
packing. For the already frozen exact artifact, the release driver has an explicit compatibility
boundary: before production preflight, quiesce or backup it accepts only regular 0644/0664 files as
canonical 0644 and regular 0755/0775 files as canonical 0755. It emits a sorted, exact 307-path mode
evidence file and validates the extracted tree against it. This bundle contains only reviewed
runtime source, not secrets: restrictive 0600/0700 therefore represents an unreviewed file class
rather than a permission improvement and is rejected with every other unknown mode. Any other
mode, special bit,
world-write, non-regular member, duplicate, unsafe path or path-set drift fails closed. A follow-up
review found that the first implementation applied this policy only to regular members: an unsafe
directory mode could still reach `tar --same-permissions`, and final-component-only symlink checks
did not exclude a nested destination ancestor symlink. The corrected gate accepts archive
directories only as 0755/0775 before extraction, including any explicit root entry. The current
destination and extracted source must resolve exactly beneath physical roots and remain regular
non-symlinks in the same executable class. Overlay consumes only file evidence, installs every
member explicitly as 0644 or 0755 into a generated root-only sibling, atomically replaces the
destination without target dereference, and verifies the anchored result's canonical mode and
ownership before the final manifest hash. Thus a final-component symlink race cannot redirect the
copy, group-write never reaches production and directories are never overlaid. The harness now
covers the exact archive, both accepted file/directory variants,
rejected permission/special/type-bit classes, unsafe evidence, nested-parent symlinks,
destination-class drift, a real canonical `install` result and a successful no-op fake that must
still fail.

### Production active-tree mode mismatch

The next authorized driver invocation failed before lock acquisition, quiescence or backup while
`assert_previous_source` compared archive-derived canonical mode classes with the current active
source tree. Driver phase state was `backup_ready=0`, `tags_changed=0`, `overlay_changed=0`; its
recovery path completed without consuming a backup.

A separately authorized single read-only diagnostic used the exact protected stage archive and the
staged driver's source-only `validate_source_manifest` / `validate_source_archive_modes` functions.
Canonical evidence was streamed directly into a bounded active-destination inspector; no remote
temporary file was created. All 307 expected destinations were present regular files owned by
`ubuntu:ubuntu`, and all 307 resolved within physical `/opt/edu-ai-lead-agent`. The exact totals
were:

- archive canonical evidence: 295 mode 0644 and 12 mode 0755;
- current active destinations: 295 mode 0600 and 12 mode 0700;
- exact-mode matches: 0; mismatches: 307; executable semantics still align for all 307 paths.

The first sorted mismatch was `.env.example`, current 0600 versus canonical 0644. The bounded first
20 mismatch rows all had the same non-executable 0600-versus-0644 shape, including `Makefile`,
`README.md`, Docker inputs and early Alembic files; output was intentionally truncated after 20.
No file content, checksum, environment value or secret was read into the diagnostic output.

This establishes that the failure is not a single-file anomaly and not candidate archive drift.
The prior active deployment stores the complete source tree in restrictive protected classes
0600/0700, whereas the archive policy derives candidate semantic classes 0644/0755. The driver
failed closed before any mutation, but the comparison itself incorrectly treated semantic class as
an exact destination permission. Compatibility for restrictive destination modes therefore needed
an independently specified preservation contract rather than a wider candidate-mode install.

## Destination restrictive-mode break-loop

### 1. Root cause category

- **B — Cross-boundary contract:** archive mode evidence describes whether candidate content is
  executable, while the active tree's mode describes its deployed access policy. One predicate was
  used for both representations.
- **E — Implicit assumption:** the first archive-mode correction assumed candidate canonical
  `0644/0755` was also the desired destination mode. It did not model `0600/0700` as a valid,
  stricter deployment policy with the same executable semantics.
- **D — Test coverage gap:** the fake overlay used group-writable or canonical destinations and
  asserted installation as `0644/0755`; it had no production-shaped `295x0600 + 12x0700` tree,
  mixed preserved-mode case or exact preflight-to-overlay mode binding.

### 2. Why the previous fix failed

The earlier fix correctly normalized the candidate archive and stopped copying group-write bits,
but it was incomplete in scope: it replaced incidental candidate permissions with a canonical
installation permission. That would have broadened every real production file had the preflight
not rejected first. The fail-closed check prevented mutation, but its shared mental model could not
distinguish semantic executable class from destination least privilege.

### 3. Prevention mechanisms

| Priority | Mechanism | Specific action | Status |
| --- | --- | --- | --- |
| P0 | Architecture | Separate candidate semantic validation from destination permission validation | DONE |
| P0 | Runtime evidence | Bind exact path + semantic class + preserved destination mode + owner/group before quiesce; revalidate before replacement | DONE |
| P0 | Least privilege | Install below a root-owned non-writable same-filesystem parent, atomically preserve `0600/0644/0700/0755`, and verify mode/owner/group/realpath/content afterward | DONE |
| P0 | Test coverage | Exercise real 0664/0775 candidate bytes against a restrictive 307-file destination, mixed modes, evidence/temporary-path ownership, TOCTOU and nested/final symlinks | DONE |
| P1 | Artifact process | Continue normalizing future candidate archives to semantic `0644/0755`; never infer active-tree permissions from them | DONE |

### 4. Systematic expansion

- **Similar issues:** owner/group and realpath are also destination policy, so they are captured at
  preflight and rechecked immediately before and after atomic replacement.
- **Design improvement:** mode evidence is now a typed semantic-mode/destination-mode/owner/group/
  path cross-boundary record instead of one number reused by archive, extraction and installation.
- **Process improvement:** release harnesses must use a production-shaped active-tree permission
  fixture, not only artifact-shaped permissions.

### 5. Knowledge capture

- [x] Updated the backend release quality contract and task deployment design.
- [x] Added exact synthetic 307-file and mixed/negative/TOCTOU regressions.
- [x] Preserved the pre-backup failure and read-only diagnosis as historical evidence.

## Trusted atomic-install parent mismatch

The next authorized retry passed current restrictive-mode compatibility, completed a fresh backup,
passed post-load candidate checks and reached the atomic source overlay. It then failed closed as
`trusted install parent ownership or mode is unsafe`, with `backup_ready=1`, `tags_changed=1` and
`overlay_changed=1`; phase-aware recovery restored prior overlay, tags and services.

The driver sets `destination_root=/opt/edu-ai-lead-agent` and derives
`source_install_tmp_parent=dirname(destination_root)`, exactly `/opt`. A bounded read-only stat
diagnosis established:

- `/opt`: directory mode 0750, uid/gid 1000:1001, owner `ubuntu:ubuntu`, device 64770, physical
  realpath `/opt`, not a symlink;
- `/opt/edu-ai-lead-agent`: directory mode 0700, the same uid/gid, owner, device and physical-path
  properties.

The trusted-parent assertion requires uid/gid 0:0 before checking group/world-write and filesystem
identity. Thus the exact failure is `/opt` ownership, not a symlink, writable-mode or cross-device
condition. The protected application directory is intentionally owned by `ubuntu:ubuntu`; deriving
the install trust anchor solely from its parent introduced an environment-specific root-ownership
assumption.

A follow-up read-only stat query found three paths that meet only the mechanical predicate
root-owned, non-group/world-writable, physical non-symlink directory on device 64770:

- `/var/backups/edu-ai/releases` — root:root mode 0700;
- `/var/backups/edu-ai` — root:root mode 0700;
- `/var/backups` — root:root mode 0755.

`/var/tmp` and `/tmp` are root:root on the same device but mode 1777 and therefore fail the trust
predicate. This inventory does not select or authorize a new temporary parent; path purpose,
collision isolation, cleanup and recovery semantics still require independent design/review.
Neither diagnosis listed directory contents or changed any filesystem state.

## Trusted backup-root correction break-loop

- **E — Implicit topology assumption:** same-device atomicity was incorrectly coupled to an
  assumption that `dirname(APP_DIR)` was root-owned.
- **D — Test gap:** the synthetic application parent was root-owned 0700, unlike production's
  `ubuntu:ubuntu` 0750 `/opt`.
- **B — Boundary gap:** the reviewed backup root already owned the required root-only trust domain,
  but overlay derived a separate trust boundary.

The driver now uses fixed `BACKUP_ROOT`, validates it as physical non-symlink root:root 0700 and
same-device before any stop, rejects every reserved-prefix object and propagates stale-scan errors,
and revalidates every exact six-alphanumeric root:root 0700 child before atomic replacement. EXIT
cleanup requires the unchanged physical trusted root and direct-child shape, so it cannot follow a
root symlink or match backup/unrelated directories. Tests reproduce non-root 0750 application
ancestry and reject the old derived parent, missing/symlink/non-root/0750/1777/cross-device roots,
directory/file/symlink/long-prefix residue and a failing scan. Backup IDs and temporary prefixes are
disjoint. This captures the 081242 recovery/read-only topology evidence and prevents security roots
from being selected by `dirname()` proximity.

## Bug Analysis: OCR fixture wrapper split one Docker invocation into commands

### 1. Root Cause Category

- **E — Implicit assumption:** the wrapper formatted `docker_call create` and its arguments on
  separate lines inside `$()` without continuations. Bash treats those newlines as command
  separators, so only `create` reached the wrapper and `--name`, `--network`, the image ID and
  runner path were executed as separate commands. The indentation was visual only.
- **D — Test coverage gap:** `bash -n` accepted the valid-but-wrong command list and the Python
  runner test bypassed the container wrapper. The fake `docker_call` used `$*` membership checks
  instead of exact argc/order checks and relied on `errexit`, whose behavior is suppressed through
  a function invoked from a guarded assignment. The focused harness ultimately caught the error,
  but redirected diagnostics were deleted by its unconditional temporary-directory cleanup, so
  the outer symptom was an unexplained exit 1.

### 2. Why the earlier gates did not diagnose it

1. Syntax validation proved only that every separated line was legal shell syntax; it could not
   prove that the lines belonged to one argv.
2. Runner tests proved the Python evidence schema but did not traverse Bash argument assembly.
3. The container harness retained neither a redacted phase/action summary nor diagnostic hashes
   before cleanup, hiding the discriminating `--name: command not found` evidence.

### 3. Prevention Mechanisms

| Priority | Mechanism | Specific action | Status |
| --- | --- | --- | --- |
| P0 | Architecture | Build multi-line wrapper commands in an argv array and invoke once with `"${args[@]}"`; otherwise require an explicit continuation on every line | DONE |
| P0 | Test coverage | Make fake Docker calls fail explicitly unless exact argc and every positional argument match; test both missing and reordered argv | DONE |
| P0 | Diagnostics | Before temp cleanup, emit only stable case/status/action names and stdout/stderr byte-count + SHA-256 evidence; never print raw stderr/argv | DONE |
| P1 | Static review | Reject newline-indented wrapper invocations that have neither an argv array nor explicit continuations | DONE |

### 4. Systematic Expansion

- **Similar issues:** a scoped multiline search found no remaining `docker_call` invocation with a
  bare newline before an option; the rule applies to all release/provider command wrappers.
- **Design improvement:** command construction and execution are now separate: the array is the
  reviewable argv contract and the fake validates it positionally.
- **Process improvement:** a harness failure must leave a content-free outer diagnostic before its
  private temporary evidence is removed.

### 5. Knowledge Capture

- [x] Updated the backend shell/release quality contract; no matching
      `src/templates/markdown/spec/` directory exists in this repository, so no template was
      invented.
- [x] Strengthened the existing local-only fake and redacted diagnostic probe.
- [x] `bash -n` passed for both scripts and the focused harness passed
      `exact-argc-order`, `redacted-failure-diagnostics`, `named-no-rm`, `network-none`,
      `pass-evidence`, `typed-fail-evidence`, `stderr-hash-only`, `cleanup-after-evidence`,
      `malformed-retained`, and `preflight-no-docker`.

## OCR-independent diversity decision after the morning failure

The user reported that a valid 1024×1024 PNG reached Zhipu OCR but was rejected locally with
`image_ocr_contract_element_extra`. The initially proposed response was to ignore unknown layout
element extension fields. Before any such code was written, the user superseded that direction:
OCR is no longer a required product gate for controlled visual diversity, and the strict parser
must remain unchanged.

The cross-layer cause of the operational dependency was the Settings invariant that rejected
`IMAGE_DIVERSITY_ENABLED=true` unless `IMAGE_OCR_ENABLED=true`. The material worker already had an
independent conditional branch: with OCR disabled it performs no recognition call and continues
from raster validation to enabled audit, similarity, storage, and persistence. The smallest change
is therefore to remove the startup dependency, while enforcing the reviewed `glm-ocr` model only
when OCR is actually enabled.

This is an explicit product tradeoff rather than evidence that the provider extension is safe or
that the rejected image had exact text. With OCR off, the prompt/brief still carries the finite
three-line contract, but the rendered pixels are not verified for missing, unexpected, duplicate,
or misordered text. Media signature/size/dimensions, provider identity, enabled visual audit,
perceptual similarity, and immutable-storage integrity remain independent acceptance gates.

Prevention mechanism: optional external quality gates must have independent activation semantics.
Settings tests now cover diversity-on/OCR-off, and the material regression proves zero recognizer
calls plus continued similarity/storage success. OCR-on parser and exact-text contract tests remain
the fail-closed boundary for any future explicit OCR activation.
