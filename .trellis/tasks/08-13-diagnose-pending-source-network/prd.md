# Diagnose and restore CAST/EdSurge production DNS

## Goal

Restore real public DNS answers for the approved CAST and EdSurge source hosts so the existing
safe fetcher can perform their bounded production activation checks without weakening SSRF,
Fake-IP, host/path, redirect, response, or anti-bypass protections.

## Confirmed facts

- The runtime is WSL2 and uses the generated resolver `10.255.255.254`.
- On 2026-08-13, both the WSL host and running Compose containers resolve
  `www.cast.org.cn` to `198.18.1.78` and `www.edsurge.com` to `198.18.1.79`.
- Python classifies both answers as non-global. The production safe fetcher therefore correctly
  raises `PolicyRejectedError(code="non_public_address")` before sending an HTTP request.
- Control hosts such as `www.gov.cn` and `education.news.cn` resolve to real globally routable
  IPv4/IPv6 answers in the same environment. This rules out a general Docker resolver outage.
- Clash Verge Rev is running through Windows service `clash_verge_service`. The current remote
  profile `Rp1pEZM1ufL7` uses merge template `profiles/moQE0hDIEMse.yaml`.
- That merge template already excludes the approved government, education, research, media, and
  Comfly hosts from Fake-IP synthesis, but it does not contain `+.cast.org.cn` or `+.edsurge.com`.
- CAST and EdSurge connectors and fixtures are approved but remain in `PENDING_SOURCE_SEEDS`.
  They must not enter normal seeding or scheduling until each passes an independent bounded live
  entry plus at-most-one-detail gate.

## Requirements

- Fix the DNS representation at the active Clash/Mihomo layer; do not change application public-IP
  validation or treat `198.18.0.0/15` as routable.
- Back up the exact active merge template before changing it, then add only
  `+.cast.org.cn` and `+.edsurge.com` to `dns.fake-ip-filter`.
- Reload only the active Clash Verge service/configuration needed for the two additions. Preserve
  unrelated proxy profiles, routing rules, DNS entries, services, and application data.
- Verify both names return only globally routable answers from WSL and Compose. Verify a known
  control source still resolves and the safe fetcher still rejects a non-global test answer.
- Run one production-safe entry request and at most one approved detail request for CAST, then the
  same bounded gate for EdSurge. Preserve HTTPS, exact host/path allowlists, redirect validation,
  timeout, response-size, content-type, language, parser-drift, and no-bypass controls.
- Record safe status, response size, discovered-item count, selected title/path shape, parser
  result, and any typed failure. Do not record response bodies, cookies, credentials, proxy URLs,
  or unrelated profile secrets.
- Keep CAST and EdSurge pending during this task even if the live gate passes. Report whether each
  is ready for a separately reviewed source-activation change.

## Acceptance criteria

- [ ] The active merge template has a timestamped backup and exactly the two scoped additions.
- [ ] After reload, WSL and Compose resolve both approved hosts to globally routable addresses,
      not `198.18.0.0/15`, private, loopback, link-local, metadata, reserved, or multicast space.
- [ ] Existing SSRF/Fake-IP tests remain green and no application security policy is relaxed.
- [ ] CAST completes an HTTPS entry request and at most one approved detail request, or produces a
      precise typed external failure unrelated to local Fake-IP DNS.
- [ ] EdSurge completes an HTTPS entry request and at most one approved detail request, or produces
      a precise typed external failure unrelated to local Fake-IP DNS.
- [ ] Fixture/connector tests remain green and the active registry remains 10 active / 2 pending.
- [ ] A rollback check confirms removing only the two additions and reloading Clash would restore
      the pre-change configuration.

## Out of scope

- Allowlisting `198.18.0.0/15`, disabling DNS/IP validation, replacing the safe fetcher, using an
  arbitrary resolver inside application code, or bypassing CAPTCHA, WAF, robots, login, paywall,
  rate-limit, or other access controls.
- Changing unrelated Clash profiles, proxy nodes, routing behavior, WSL global networking, Docker
  networking, source parser rules, application APIs, database schema, scoring, or generated copy.
- Moving CAST or EdSurge into `SOURCE_SEEDS`, seeding them, or enabling scheduled acquisition.

## Risks and rollback

- A Windows service reload may require elevated service permission. If it is unavailable, stop
  after preserving the prepared backup/change evidence and report the exact operator action; do
  not seek an unsafe alternative.
- A host may resolve publicly but still reject, challenge, redirect, or drift during the bounded
  smoke. Such a failure keeps the source pending and must not trigger retries or bypasses.
- Rollback removes only `+.cast.org.cn` and `+.edsurge.com` from the active merge template, reloads
  `clash_verge_service`, and confirms the template matches its backup aside from those two lines.
