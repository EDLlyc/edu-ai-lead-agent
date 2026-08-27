# Design

## Boundaries

This change is a narrow cross-layer extension of the existing IP creation flow. It keeps the shared image-generation default bounded while allowing the IP application to opt into an extended prompt policy explicitly.

## Prompt contract

1. Remove `minLength={8}` and `maxLength={2000}` only from the IP creation textarea; retain native `required`.
2. Remove both length constraints only from `IpAssetGenerationRequest.prompt` and reject normalized blank input in the IP application boundary.
3. Extend the shared prompt validator with explicit optional minimum and maximum values. Its defaults remain 8 and 2,000 characters.
4. Add an explicit request-level unrestricted-length policy to the provider-neutral `ImageGenerationRequest`, defaulting to false.
5. The IP worker sets that policy. Every image generator adapter validates through one shared request helper so direct/fake/live paths behave consistently while still rejecting a normalized blank prompt.
6. Existing non-IP call sites rely on the default false value and therefore keep their current 8–2,000 character contract.

The normalized full prompt remains part of the durable generation fingerprint and job row. Real
PostgreSQL validation found the existing column was `varchar(2000)`, so Alembic `20260827_0037`
widens it to `TEXT`. Downgrade refuses before any type change when a stored prompt exceeds 2,000
characters and never truncates user content.

## UI direction

Keep the established editorial atelier rather than introducing a new theme. Use a restrained local sans stack for navigation, labels, and numerals; keep the existing editorial serif role for the large page title. The signature move is a thin rule connecting compact section metadata, used consistently in the brief and dark output panels.

- Back control: bordered arrow tile plus a two-line label (`ASSET LIBRARY` / `返回共享图库`).
- Brief label: separate `01` badge, hairline, and `创作简报` label.
- Output label: separate `OUTPUT`, hairline, and `私人结果`, with inverse colors.
- Filmstrip: compact rounded-rectangle tabular number badge, visually related to the chapter badge without looking identical.

All markup remains semantic, visible focus remains global, and no remote fonts/assets are introduced.

## Compatibility and rollback

- Migration `0037` changes only the prompt column type and preserves all existing job text.
- Existing request fingerprints remain stable for prompts at or below 2,000 characters because normalization does not change.
- Removing the IP schema maximum changes only OpenAPI validation metadata; TypeScript remains `string`.
- Rollback restores the IP schema/frontend minimum and maximum and removes the request opt-in flag.
  Database downgrade is allowed only when every stored prompt fits `varchar(2000)`; otherwise it
  fails safely without truncation.
