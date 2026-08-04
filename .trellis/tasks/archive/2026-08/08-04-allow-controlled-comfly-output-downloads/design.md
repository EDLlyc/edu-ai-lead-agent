# Technical Design

## Boundary and configuration

Add `comfly_allow_public_output_urls: bool = False` to `Settings`, expose it as
`COMFLY_ALLOW_PUBLIC_OUTPUT_URLS` in Compose and `.env.example`, and pass it through the AI
factory into `OpenAICompatibleImageGenerator`. The default remains closed; the local ignored
`.env` used for the live smoke enables the setting explicitly.

`COMFLY_OUTPUT_HOSTS` continues to represent exact bare hostnames. An output URL whose hostname is
in that set uses the existing trusted-host path. An unlisted hostname is eligible only when the new
Comfly setting is enabled and its destination is proven to be public.

## URL policy

The generator will validate the URL before opening a stream:

1. Require HTTPS, hostname, default/443 port, no userinfo, no fragment, and no whitespace.
2. Permit an exact configured output host without DNS preflight, while retaining content and
   response checks.
3. For an unlisted host in opt-in mode, reject literal non-global IP addresses and resolve the
   hostname through an injected async resolver. Every resolved A/AAAA address must be globally
   routable; an empty or failed resolution is rejected.
4. Use `follow_redirects=False`, bounded timeout/retries, and the existing byte/content-type/image
   validation pipeline. Signed URL query parameters remain intact because only fragments and
   malformed URL components are rejected.

The resolver is injected for deterministic tests. Production resolution runs off the event loop
through the standard library thread boundary, satisfying the async I/O rule without adding a DNS
dependency. This is a practical preflight defense; the service still does not follow redirects or
accept a non-public literal address.

## Data flow

```text
Comfly generation response
        |
        v
extract one URL/base64 representation
        |
        v
URL policy -> exact host OR opt-in public DNS policy
        |
        v
bounded HTTPS stream -> media/signature/size/dimension checks
        |
        v
ImageGenerationResult -> existing MinIO/database artifact pipeline
```

No new persistence or API contract is needed. A policy failure remains the existing typed image
output validation failure, and no bytes are returned to the storage layer.

## Compatibility and rollout

- Existing deployments with `COMFLY_OUTPUT_HOSTS` continue to work unchanged.
- Deployments with the new setting absent remain closed to unknown output hosts.
- The local deployment explicitly opts in, then restarts API/content-worker before the live smoke.
- If the provider returns a private address, malformed URL, unsupported body, or transient HTTP
  failure, the current typed failure/retry behavior remains the source of truth.
- Rollback is a config-only disable (`COMFLY_ALLOW_PUBLIC_OUTPUT_URLS=false`) followed by service
  restart; code rollback is not required to stop unknown-host downloads.

## Verification

Focused tests cover exact hosts, disabled unknown hosts, enabled public hosts, resolver failures,
private IPs, and the existing redirect/size/media/dimension paths. The final gate uses the backend
quality commands, Compose rendering, doctor, and a real provider smoke only after deterministic
checks pass.
