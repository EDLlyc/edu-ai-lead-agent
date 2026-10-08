# 新闻源后台增删改（运营后台第 1 项）

Parent `10-08-admin-console`. Planned 10/9–10/14 (3 d). Needs item 0.

## Today

- Sources are code: `SOURCE_SEEDS` (10 active) and `PENDING_SOURCE_SEEDS` (3) in
  `backend/app/infrastructure/ingestion/source_profiles.py`.
- `python -m app.seed_sources` runs on every deploy (`compose.yaml`). `seed_sources`
  (`infrastructure/db/repositories.py`) forces `enabled=True` for seeds and `False` for pending
  ones, so any database toggle is overwritten at the next deploy.
- `create_run` fetches every enabled source that has an active version. `cadence` is stored but
  not used.
- Each source needs a connector entry (`CONNECTORS` in `infrastructure/ingestion/connectors.py`):
  - The generic ones are `GovernmentJsonConnector` and `HtmlConnector` (link regex + content and
    discovery selectors).
  - Some sources need custom date or link functions.
  - There is no RSS connector.
- A `SourceVersion` is immutable. Its fingerprint covers URL, hosts, tier, rule version and
  priority policy.

## Scope

- List: name, tier, connector, entry URL, enabled, last fetch result (count, filtered, errors).
- Enable / disable a source.
  - `seed_sources` must stop overwriting an operator's choice: the seed sets `enabled` only when
    the source is first created.
  - Record who changed it.
- Edit the safe fields: display name, priority policy, tier A/B. Saving creates a new source
  version, never edits one in place.
- Add a source with a generic `HtmlConnector` (entry URL, allowed host, link pattern, content
  selector) or an RSS feed (new generic RSS connector).
  - Before saving, a **dry run** fetches the entry page and shows the first 5 articles it would
    take, with title, date and body length.
  - A new source starts disabled until the operator enables it.
- Delete means archive: hidden, not fetched, history kept (evidence rows reference it).
- Every change writes `admin_audit_events`.

## Risks / guards

- An arbitrary URL fetch from the admin UI is an SSRF path.
  - Allow only http(s) on public hosts (no private, loopback or link-local IPs after DNS) and
    obey robots.
  - Apply the same rate limit as acquisition.
- A broken new source must not break the run. Per-source failures are already isolated; verify
  this.

## Open

- Which sites does the teacher want to add first? Use them as the acceptance examples.
