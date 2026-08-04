# Zhipu GLM-OCR research

## Official contract checked on 2026-08-03

- Guide: <https://docs.bigmodel.cn/cn/guide/models/vlm/glm-ocr.md>
- API reference: <https://docs.bigmodel.cn/api-reference/%E6%A8%A1%E5%9E%8B-api/%E6%96%87%E6%A1%A3%E8%A7%A3%E6%9E%90.md>
- Endpoint: `POST https://open.bigmodel.cn/api/paas/v4/layout_parsing`
- JSON request: `{"model":"glm-ocr","file":"<url-or-data-uri>"}`
- The API accepts PDF/image URL or Base64 input, PDF up to 50 MB and 100 pages, and returns
  `md_results`, `layout_details`, `data_info`, `usage`, and request metadata.
- The brand ingestion path needs only `md_results`; crop images and layout visualizations stay off.
- The separate `/api/paas/v4/files/ocr` service is an image-only, 8 MB hand-writing OCR tool and is
  not appropriate for the supplied multi-page PDFs.

## Selected integration

Use the immutable MinIO bytes as a `data:application/pdf;base64,` value in the layout-parsing
request. This avoids exposing a private object URL to the provider and fits both supplied files
(approximately 25 MB each) within the documented PDF limit. The adapter must bound the raw input,
encoded request, response bytes, timeout, concurrency, and retries.

Local `pypdf` extraction remains the default. A configurable sparse-text rule decides when a PDF
needs OCR, based on total extracted characters and characters per page. OCR output is normalized,
chunked, and embedded exactly like local text; it is not factual evidence and is never logged.
