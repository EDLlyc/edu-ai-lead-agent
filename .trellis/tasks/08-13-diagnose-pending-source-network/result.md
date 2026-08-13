# Implementation result

## Status

Completed within the reviewed diagnostic scope. The administrator reload applied the scoped Clash
merge-template change, and every required resolver path now returns real globally routable answers
for CAST and EdSurge. Both bounded entry requests reached their sites successfully, but each
approved connector then raised typed `parse_failure` during deterministic discovery. Neither
source made a detail request, and both remain pending and not ready for activation.

## Safe operational evidence

- Immediately before editing, `profiles.yaml` still selected `Rp1pEZM1ufL7`; that profile's
  `option.merge` still selected `moQE0hDIEMse`.
- The original merge template SHA-256 was
  `b1a35fada018c4a25144385860449b717d83f245550cff17947e2193b5662e0f`.
- Backup:
  `/mnt/c/Users/12297/AppData/Roaming/io.github.clash-verge-rev.clash-verge-rev/profiles/moQE0hDIEMse.yaml.bak-20260813T161610+0800`.
  It was byte-identical to the original and has the same SHA-256.
- The edited YAML has one `dns.fake-ip-filter` list with 12 items and exactly one occurrence each
  of `+.cast.org.cn` and `+.edsurge.com`. The diff against the backup contains only those two added
  list items. Its SHA-256 is
  `83374f0248bb7905398edde674dd8dd358785d158059a615b5580eddc596d573`.
- After the original non-elevated reload was denied, the user completed the same reviewed reload
  with administrator approval. An independent read-only check reports `clash_verge_service` as
  `Running`; no application, PostgreSQL, MinIO, Docker, or WSL restart was part of the continuation.
- WSL resolved CAST to globally routable IPv4 answers in the observed DNS pools
  `116.196.154.139`, `123.134.185.19`, `27.222.17.240`, `211.91.76.144`, and `211.95.37.91`;
  EdSurge resolved to `34.195.152.160` and `34.202.247.201`.
- The already-running PostgreSQL and MinIO containers returned globally routable answers for both
  targets. The application `validate_public_resolution` path independently accepted both targets.
  No observed target answer was non-global or in `198.18.0.0/15`.
- WSL, both containers, and the application path also continued to accept `www.gov.cn` and
  `education.news.cn` as public controls, including the globally routable IPv6 answers visible to
  WSL and the application.

## Bounded pending-source gates

Each source used its existing `PENDING_SOURCE_SEEDS` profile, `SafeHttpFetcher`, resolver checks,
HTTPS/host/path/redirect/size/content-type controls, and approved connector. Discovery used
`limit=1`. A source stopped immediately on its first typed failure, without retry or bypass.

| Source | Entry result | Discovery / selection | Detail result | Profile contract | Readiness |
|---|---|---|---|---|---|
| CAST | HTTP 200; `text/html`; 20,077 bytes; final path `/kp/` | `ParseError(code="parse_failure")`; 0 approved items; no selected title or article path | Not requested | `zh-CN`; parser `1.0.0` | Not activation-ready |
| EdSurge | HTTP 200; `text/html`; 108,277 bytes; final path `/coverage-areas/artificial-intelligence` | `ParseError(code="parse_failure")`; 0 approved items; no selected title or article path | Not requested | `en`; parser `1.0.0` | Not activation-ready |

The network defect is resolved. The remaining blocker is live list-page parser drift: neither page
produced an article URL matching its reviewed discovery scope and allowlist. Any connector change
and repeat live gate require separate review; this task did not inspect around, relax, or bypass
the approved parser and policy boundaries.

## Source and data safety

- Code registry: 10 entries in `SOURCE_SEEDS`, 2 entries in `PENDING_SOURCE_SEEDS`.
- Database: 10 enabled rows out of 10 total source rows, no CAST/EdSurge rows, and no CAST/EdSurge
  acquisition jobs.
- Only PostgreSQL and MinIO are running under Compose; the acquisition scheduler and worker remain
  stopped. No seed, schedule, database mutation, source activation, or product-code change was
  performed.

## Validation

- Focused contract suite: 37 passed across `test_safe_fetcher.py`, `test_fetch_policy.py`,
  `test_live_smoke.py`, and `test_source_connectors.py`.
- `make doctor`: passed, including 10 approved active source profiles and healthy PostgreSQL and
  MinIO services.
- `git diff --check`: passed.
- Final audit found no application security-policy relaxation, no secrets added to task artifacts,
  and no edits to the pre-existing dirty files under `.agents/skills/` or `reports/`.

## Readiness conclusion

The Clash/Fake-IP repair is ready to remain in place: target DNS and public controls pass in all
required contexts, and the existing application protections remain unchanged. CAST and EdSurge
must stay in `PENDING_SOURCE_SEEDS`; neither is ready for a separately reviewed activation change
until its live discovery parser is reviewed and the bounded entry plus at-most-one-detail gate is
rerun successfully.

## Rollback

To discard the operational change, first verify the active profile/template association has not
changed, copy the timestamped backup above over `moQE0hDIEMse.yaml`, verify the restored SHA-256 is
`b1a35fada018c4a25144385860449b717d83f245550cff17947e2193b5662e0f`, and reload only
`clash_verge_service` from an elevated Windows PowerShell. A two-line reverse diff is the expected
rollback shape. No application or database rollback is required.
