# Enterprise WeChat Official API Research

Research date: 2026-08-05

Sources:

- [获取 access_token](https://developer.work.weixin.qq.com/document/path/91039)
- [上传临时素材](https://developer.work.weixin.qq.com/document/path/90253)
- [发送应用消息](https://developer.work.weixin.qq.com/document/path/90236)

## Access token

The official self-built application endpoint is:

```text
GET https://qyapi.weixin.qq.com/cgi-bin/gettoken?corpid=ID&corpsecret=SECRET
```

The success response contains `errcode=0`, `errmsg=ok`, `access_token` and `expires_in`; the documented normal lifetime is 7200 seconds. The official page explicitly says to cache the token, distinguish tokens by application, keep it on the server, and refresh it when it expires or is invalidated early. The adapter therefore keeps a process-local cache and never persists or logs the token.

## Temporary image media

The official endpoint is:

```text
POST https://qyapi.weixin.qq.com/cgi-bin/media/upload?access_token=ACCESS_TOKEN&type=image
```

The request is `multipart/form-data` with the file field named `media`. The response returns a temporary `media_id`, valid for three days. The official limits state that an image must be larger than 5 bytes, no larger than 10 MB, and must be JPG or PNG. The adapter validates the input before upload and does not persist the temporary media id.

## Application messages

The official endpoint is:

```text
POST https://qyapi.weixin.qq.com/cgi-bin/message/send?access_token=ACCESS_TOKEN
```

The text and image message bodies contain `touser`, `msgtype`, `agentid`, and the corresponding `text.content` or `image.media_id`. The official response returns `errcode`, `errmsg`, and, on success, `msgid`; it can also report invalid or unlicensed users. The adapter records only bounded safe error codes and provider request ids.

The official page supports `enable_duplicate_check=1` and a `duplicate_check_interval` with a documented default of 1800 seconds. The first version enables duplicate checking for both message kinds. The documented message frequency limit and the possibility of partial invalid recipients are treated as provider errors; the first version has one configured recipient, so a non-zero recipient error is terminal rather than silently redirected.

## Implementation consequences

- All requests use HTTPS and an allowlisted `qyapi.weixin.qq.com` host.
- `access_token` is placed only in the URL generated inside the adapter and is redacted from logs; it is never returned to API clients.
- A successful text call is persisted before the image call. A timeout around a send call is classified as `delivery_unknown`, because the provider may already have accepted the message.
- A token-invalid response can invalidate the in-memory token and retry the same call once. Rate limits and temporary server failures use bounded backoff. Unknown outcomes are never automatically retried.
- No callback endpoint is needed for this one-way internal application-message flow.
