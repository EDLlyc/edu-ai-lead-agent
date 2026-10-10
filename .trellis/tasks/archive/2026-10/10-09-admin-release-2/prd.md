# 运营后台合并上线（完善项 + 第 3/4/5/6/8 项）

Parent `10-08-admin-console`.

## Goal

Ship everything finished since the 10-08 release in one overlay on the running image:
- the polish;
- 公众号账号 / 发布 / 数据;
- 排版模板;
- 模型配置.

It touches the same six services as before, runs migrations 0055–0059, and adds two server keys.

## Findings that shape it (2026-10-09, read-only checks)

- Production runs two images. Six services run `5a5fb24c` (10-08). Seven run `83a41e41` (09-28):
  the 公众号 pipeline, governance, and the acquisition and weekly schedulers.
  - 排版模板 needs the draft worker, so it is stored but not applied until that pipeline is
    upgraded. The page says so.
  - Model key rotation reaches 3 of the 6 key holders. The page shows each service's reported
    version and lists the others as 未接入. Env keys must stay valid.
- The server `compose.yaml` maps env per service, so the keys need explicit lines.

## Acceptance

- `rollout/README.md` steps 1–11 pass.
- The production 公众号 is bound via `import-env` (step 12).
- No publish is made without the owner's word.
- `mainline` is fast-forwarded and the other sessions are told.

## Out of scope

- Upgrading the 公众号 pipeline / governance services: a separate release, because its image
  lineage differs from `mainline`.
- Public HTTPS access (needs the domain answers from the tech lead).
- Item 7 海报风格.
