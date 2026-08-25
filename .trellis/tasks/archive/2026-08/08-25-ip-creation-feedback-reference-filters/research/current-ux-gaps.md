# Current UX and contract evidence

- `IpAssetCreationPage.tsx` keeps `announcement` in a `visuallyHidden` status node, so favorite,
  enqueue, and download acknowledgements are not visibly perceivable.
- Reference cards expose selection only through the action button's `aria-pressed` state and label;
  the card itself has no selected class, check indicator, or stable `01`–`03` badge.
- The picker uses only `useIpAssets` with a text query. The separate personal shelf already proves
  `usePersonalIpAssets` for `favorite`, `uploaded`, and `generated` sources.
- The personal-list API is cursor-backed and returns safe card projections plus membership/favorite
  state. No new backend route is needed for reference source filters.
- Backend generation validation accepts only distinct shared-ready references. Personal favorites
  can include an owned private asset, so the picker must explicitly apply both shared and ready
  predicates before rendering candidates.
- `OutputStage` currently merges queued and running into “模型正在组合…”. The durable job model and
  polling response already distinguish `queued` from `running`, allowing honest copy without a new
  API field.
- `generation_available` is computed from feature flags and runtime provider presence. It is not a
  worker heartbeat; the UI must not treat it as worker-online evidence.
- Local operational evidence on 2026-08-25: configured provider `comfly`, model `gpt-image-2`, one
  queued generation, one succeeded generation, and no running `ip_asset_worker_main` process.
