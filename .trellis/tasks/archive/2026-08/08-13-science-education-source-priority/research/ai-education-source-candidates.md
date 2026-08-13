# Science and AI education source candidates

Research date: 2026-08-13 (Asia/Shanghai)

## Selection criteria

Candidates were evaluated for topic density, authority, stable first-party listing URLs, language, article-path controllability, live reachability, robots/content signals, and fit with the current safe-fetch/fixture contract. A page appearing in search results is not sufficient for onboarding; every selected profile still needs a `SafeHttpFetcher` smoke check, bounded host/path allowlist, fixed fixtures, connector/parser version, and recorded terms review.

## Implementation activation outcome

The production `SafeHttpFetcher` activation gate was repeated on 2026-08-13 after connector and
fixture validation:

- `xinhua-education`: the controlled entry returned HTTP 200, discovery produced dated article
  paths, and one bounded detail request returned HTTP 200 with a meaningful title and body. It is
  active in `SOURCE_SEEDS`.
- `cast-science-education`: DNS preflight returned typed `non_public_address`; no HTTP request was
  sent. The connector, fixture, and proposed profile remain in `PENDING_SOURCE_SEEDS` only.
- `edsurge-ai-education`: DNS preflight returned typed `non_public_address`; no HTTP request was
  sent. The connector, English fixture, and proposed profile remain in `PENDING_SOURCE_SEEDS`
  only.

The resulting registry has ten active sources and two pending profiles toward the approved target
of twelve. The earlier reachability observations below established source/content fit but do not
override the production-safe activation result. No SSRF, DNS, redirect, path, or response policy
was relaxed.

## Recommended MVP batch

### 1. Xinhua Education / 新华教育

- Organization and tier: Xinhua education channel; recommend Tier B authoritative media.
- Language/timezone: `zh-CN`, `Asia/Shanghai`.
- Entry: <https://education.news.cn/index.htm>
- Proposed host/path boundary: `education.news.cn`; accept dated article paths matching `/<YYYYMMDD>/<32-hex>/c.html`; reject topic pages, app links, external hosts, images, and legacy HTTP unless an exact source-scoped redirect is separately proven and approved.
- Evidence: the live entry returned HTTP 200 on 2026-08-13 and included current science-education and AI-education headlines, including a current “做中学” science-education story and an AI + education conference story.
- Robots: <https://education.news.cn/robots.txt> returned HTTP 200. Review and snapshot the exact rules during implementation rather than inheriting the existing Xinhua Technology status.
- Relevance/product fit: high for science education policy/practice, AI education, school implementation, competitions, and education innovation.
- Risk: the page mixes many unrelated education topics and contains HTTP, external app, special-topic, and image links. It requires narrow discovery selectors plus the bilingual science/AI-education relevance rule before detail fetch.

### 2. China Association for Science and Technology / 中国科协科普

- Organization and tier: first-party national science organization with mixed official notices and secondary reports. Recommend Tier A only for clearly first-party policy/notice paths; if one profile cannot distinguish authorship, use Tier B for the mixed listing.
- Language/timezone: `zh-CN`, `Asia/Shanghai`.
- Entry: <https://www.cast.org.cn/kp/>
- Proposed host/path boundary: `www.cast.org.cn`; discover only explicit article routes selected from the science-popularization page. Avoid a root-wide allowlist in the final profile if stable narrower prefixes can be proven from fixtures.
- Evidence: the live entry returned HTTP 200 on 2026-08-13. The page exposes youth science education, science camps, science clubs, competitions, and science-popularization policy/activity material. Example first-party youth science content is visible at <https://www.cast.org.cn/xw/tzgg/KXPJ/art/2026/art_a92767489fdc4d90830e4b6930be6459.html>.
- Robots: <https://www.cast.org.cn/robots.txt> returned 404, so permission is not established by robots. Record `manual_review`, perform terms review, rate-limit conservatively, and do not interpret missing robots as affirmative permission.
- Relevance/product fit: high for scientific literacy, competitions, talent development, science camps, laboratory/university experiences, and project practice; medium for AI education.
- Risk: content density is broader than education and authorship can vary. Source-tier semantics must not overstate a republished article as a primary claim.

### 3. UNESCO Artificial Intelligence in Education

- Organization and tier: UNESCO first-party international organization; Tier A.
- Language/timezone: initial profile `en`, UTC (retain the exact source timezone selected during implementation).
- Entry: <https://www.unesco.org/en/digital-education/artificial-intelligence>
- Proposed host/path boundary: `www.unesco.org`; restrict to the AI-in-education landing page and article/news paths actually linked from its visible News section. Do not crawl disallowed search, explore, pagination, or query-filter routes.
- Evidence: the page exposes a dedicated current News section for AI competency, digital/AI skills, AI education observatories, and student/teacher initiatives.
- Robots/content signals: <https://www.unesco.org/robots.txt> was reachable and declares `search=yes`, `ai-train=no`, and `use=reference`; it also disallows search/explore and several query/pagination patterns. Recommend `manual_review` and reference-only use: store bounded factual evidence and citation provenance, never use it for training, bulk reproduction, or brand-source ingestion.
- Relevance/product fit: high for AI literacy, teacher/student competencies, safe and human-centred AI, international policy, and project learning.
- Risk: content-use semantics need an explicit operator/legal sign-off before activation. If the project's evidence-to-copy use is judged outside `use=reference`, defer the source rather than weakening the constraint.

### 4. EdSurge Artificial Intelligence

- Organization and tier: specialist education-technology newsroom; Tier B professional media.
- Language/timezone: `en`, use the publication timestamp/timezone exposed by the page rather than assuming China time.
- Entry: <https://www.edsurge.com/coverage-areas/artificial-intelligence>
- Proposed host/path boundary: `www.edsurge.com`; listing path `/coverage-areas/artificial-intelligence`, article path `/news/`; reject `/api/`, sponsored/advertorial items unless visibly labeled and excluded, and unrelated coverage routes.
- Evidence: the live entry returned HTTP 200 on 2026-08-13 and is explicitly described as current AI education coverage. Current reporting covers K-12 AI adoption, classroom use, teacher readiness, AI literacy, governance, and learning impacts.
- Robots: <https://www.edsurge.com/robots.txt> allows `/` and disallows `/api/`; it publishes news and coverage-area sitemaps. The implementation should still use the human-facing dedicated listing and conservative pacing, not the disallowed API.
- Relevance/product fit: high for practical AI education, teacher/classroom adoption, ethics/safety, curriculum, and student learning; medium for science education outside AI.
- Risk: sponsored stories exist. The connector/relevance policy must reject visible sponsored/advertorial labels or add a provenance flag that prevents them from supporting final evidence.

## Deferred batch

### China Education News / 中国教育新闻网

- Entry: <https://www.jyb.cn/default.html?type=pc>
- Value: Education Ministry-affiliated specialist media with strong science education, K-12 AI curriculum, classroom, and policy coverage.
- Deferral reason: TLS access was unstable from the current production-like network probe on 2026-08-13. The site is a high-priority replacement/addition once `SafeHttpFetcher` can complete list/detail smoke checks without bypasses.

### National Center for Educational Technology / 中央电化教育馆

- Entry: <https://www.ncet.edu.cn/zhuzhan/sjsyzyxw/index.html>
- Value: highly focused Tier A first-party digital/AI education news and program material.
- Deferral reason: a normal robots request received CloudWAF HTTP 418 on 2026-08-13. Do not add browser automation, cookie challenges, proxy rotation, or WAF bypass. Reconsider only when an approved feed or ordinary safe HTTP path is available.

### OECD Artificial Intelligence and Education and Skills

- Entry: <https://www.oecd.org/en/topics/artificial-intelligence-and-education-and-skills.html>
- Value: Tier A international policy/research signal, particularly AI literacy, system policy, and education outlooks.
- Deferral reason: the page was visible through ordinary web indexing but a subsequent direct automated request returned HTTP 403/Cloudflare. It is also a lower-cadence insight/publication hub rather than a daily news feed.

### European Commission Digital Education

- Entry: <https://education.ec.europa.eu/focus-topics/digital-education>
- Value: Tier A updates on AI literacy, ethical AI, teacher guidance, digital-content quality, and digital education policy.
- Deferral reason: ordinary robots and page access are available, but the listing is broader than AI/science education and lower density than the MVP sources. Add after the bilingual relevance rule is calibrated on the first batch.

### ISTE / International Society for Transforming Education

- Entries: <https://iste.org/news> and <https://cdn.iste.org/learning-library?topic=Artificial+Intelligence>
- Value: specialist educator practice, standards, AI literacy, classroom use, and safety.
- Deferral reason: the topic library mixes articles, paid courses, webinars, books, and promotional first-party material across multiple hosts. It needs a separate resource-type and commercial-content policy before becoming evidence.

## MVP activation gate

Each source is independently activated only when all of the following pass:

1. Terms/robots/content-signal review is recorded with a review timestamp and final status.
2. `SafeHttpFetcher` completes an entry and one detail request without relaxing SSRF, redirect, response, content-type, or rate-limit rules.
3. Fixed list/detail fixtures prove selectors, canonical URL, publication time, language, sponsor/authorship exclusions, and parser-drift failures.
4. The shared bilingual science/AI-education policy produces audit metadata and does not fill item quotas with unrelated content.
5. English sources pass governance quote/offset binding and Chinese-copy provenance tests.

If one recommended source fails its activation gate, omit it from the active seed registry. Any
replacement from the deferred batch requires a separately reviewed source-scope decision; never
ship a knowingly failing active seed or silently substitute another source merely to meet a count
target.
