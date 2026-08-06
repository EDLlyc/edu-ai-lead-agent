# Official Research: Enterprise WeChat Message Push

Source: [Message push (formerly group robot) configuration](https://developer.work.weixin.qq.com/document/path/91770), retrieved 2026-08-06.

## Confirmed Facts

- A creator obtains a webhook URL for the group and the server sends an HTTPS `POST` to that URL.
- The documented send endpoint is `https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=KEY`.
- This route does not use the self-built-application `CorpID`, `CorpSecret`, `AgentId`, or `touser`
  fields. It requires outbound access to the official host and the webhook key.
- Text messages use `msgtype=text`; UTF-8 content is limited to 2048 bytes.
- Markdown messages use `msgtype=markdown`; UTF-8 content is limited to 4096 bytes. The document
  also lists `markdown_v2`, but the MVP uses the simpler Markdown payload.
- Image messages use `msgtype=image` with `image.base64` and `image.md5`. The raw image bytes before
  Base64 must be no larger than 2 MiB and the supported formats are JPG and PNG.
- The documented push frequency limit is no more than 20 messages per minute.
- The `upload_media` endpoint is for voice/file media and its returned `media_id` is temporary; it
  is not the image path required by this MVP.

## Engineering Consequences

- The webhook key is a bearer credential. It must be kept in deployment secrets, excluded from logs,
  API responses, persisted job rows, task artifacts, and screenshots.
- A webhook response cannot be treated as application-level exactly-once delivery. Durable job
  fingerprints and an explicit unknown state are required when the transport outcome is ambiguous.
- The project should send Markdown and image as two bounded messages and retain its existing durable
  text-before-image ordering.
