# V6 official news-photo source selection

## Decision

The v6 local review bundle adds two contextual news photographs beside the five frozen v5 company-IP scenes. The
photographs come from exact Ministry of Education pages and are downloaded only by an explicit operator command.
They are not brand assets, do not replace evidence bindings, and are not exposed as remote `<img>` URLs.

## Frozen photo set

| Public ref | Context | Source page | Exact image | Caption and credit | Validation identity |
| --- | --- | --- | --- | --- | --- |
| `moe-basic-education-conference-20260722` | Related national basic-education meeting immediately following the validated 2026-07-21 article | `https://www.moe.gov.cn/jyb_xwfb/s6052/moe_838/202607/t20260722_1444692.html` | `https://www.moe.gov.cn/jyb_xwfb/xw_zt/moe_357/2026/2026_zt09/jdt/202607/W020260723357821146376.jpg` | “7月22日，全国基础教育工作会议在北京召开。中共中央政治局常委、国务院副总理丁薛祥出席会议并讲话。” 新华社记者 高洁 摄 | JPEG, 575×354, `0d2427caf395ba0d55eaf66678e2d67dd9bc581e2813d5860505e232c2e3811d` |
| `moe-ai-education-press-conference-20260410` | Direct visual context for the validated “人工智能+教育” policy source | `https://www.moe.gov.cn/fbh/live/2026/77927/tpwd/202604/t20260410_1433382.html` | `https://www.moe.gov.cn/fbh/live/2026/77927/tpwd/202604/W020260410433219993653.jpg` | “教育部召开新闻发布会介绍《‘人工智能+教育’行动计划》有关情况。” 中国教育报记者 张劲松/摄 | JPEG, 800×535, `ea635b7ecca51e8073ae3bd7954d8fc03234f49dda52e3a675f2591d75a7afb5` |

## Editorial and rights boundary

- The first image is explicitly labelled a related/context scene, not an image from the 2026-07-21 article.
- The second image belongs to the official same-day image-live page for the already cited AI policy event.
- Photographer/source credits and visible official watermarks are preserved. V6 does not crop, retouch or
  recompress the source bytes.
- The public pages establish provenance and captions, but not a blanket republication licence. Every v6 projection
  therefore records `rights_status=publish_permission_unverified`, and the bundle remains local-review-only until a
  human confirms permission outside this workflow.
- The final HTML uses relative local assets. Opening the preview triggers no image request to the Ministry site.

## Network and failure boundary

- The explicit operator export performs exactly two image GETs from the frozen URLs. There is one attempt per image,
  no search fallback, no arbitrary URL input and no partial ready bundle.
- HTTPS/host/exact URL, response media type, byte limit, JPEG signature/full decode, dimensions and SHA-256 all
  fail closed. The two bytes must be distinct.
- Unit tests inject fake responses and make zero external requests. The v6 command never constructs article,
  embedding, image-generation, WeChat, WeCom or publish clients.

## 2026-08-25 local acceptance result

- A direct v6 network export validated the entire v5 source and exact two-photo configuration, then the Ministry
  image origin returned a known non-200 on the first GET. The exporter stopped immediately, did not request the
  second image, did not retry and left no final or partial output.
- Both selected originals had already been acquired during source research. Their bytes matched the pinned hashes
  and dimensions above, so the final v6 bundle used the explicit validated-local-cache path.
- `run.json` reports `official_photo_get_calls=0`, `official_photo_cache_reads=2` and
  `failed_official_photo_get_attempts_before_export=1`. The adapter now sends bounded browser-compatible Accept,
  Referer and User-Agent headers for a future explicit live run, but this session did not retry the official origin.
- The installed local bundle passed 11 focused tests, Ruff, format, PyCompile, mypy, manifest/ZIP integrity and
  Chromium 430/320 checks: seven images loaded, external requests were zero and horizontal overflow was zero.
