# Ministry source research

## Probe

- Date: 2026-08-05 Asia/Shanghai.
- Request: `https://www.moe.gov.cn/jyb_xwfb/` with the project identifying User-Agent and a maximum of two redirects.
- Result: `302 Found`, `Location: http://www.moe.gov.cn/jyb_xwfb/`; following that exact same-host/path redirect returned `200 OK`, `Content-Type: text/html`, and a response body of about 64 KiB.
- No CAPTCHA, login requirement, browser challenge, or arbitrary redirect was needed for this read-only probe. This observation does not authorize anti-bot bypass.

## List shape

- Page title: `新闻 - 中华人民共和国教育部政府门户网站`.
- The current work-dynamics list is under `#one_con1`.
- Article links use paths such as `/jyb_xwfb/gzdt_gzdt/s5987/202608/t20260804_1446039.html` and are accompanied by visible `MM-DD` text.
- The article URL date can be used only as a bounded discovery hint; detail metadata remains authoritative.

## Detail shape

- Current article: `http://www.moe.gov.cn/jyb_xwfb/gzdt_gzdt/s5987/202608/t20260804_1446039.html` after the source redirect policy.
- Detail metadata contains `ArticleTitle`, `PubDate`, `publishdate`, `ContentSource`, and `SiteDomain`.
- The article body is in `.TRS_Editor`; the page also contains a visible title and source/date line.
- Current title: `教育部部署开展义务教育阶段科学教育“做中学”领航行动`.
- Current detail date: `2026-08-04 11:13`; source: `教育部`.
- Body signals include `科学教育`, `科学探究实践`, `科技发展`, `航空航天`, and `人工智能`, which should be captured as bounded relevance evidence.

## Safety conclusion

The source is suitable for a dedicated source profile with `www.moe.gov.cn` and `/jyb_xwfb/` allowlists plus a versioned HTTP fallback flag. The flag must be false for every other source and must not change public DNS validation, response limits, rate limiting, redirect validation, robots/terms recording, or the no-bypass policy.
