# 2026-09-22 胸牌修正版重新进入草稿箱证据

## 固定执行包

- published-to-redraft operator SHA-256：`d8f45981431f9946475048d80f4f21f556dcda47702e1519857a870642ce0b43`
- shared replacement dependency SHA-256：`d6501b9bc803c66d981bf4419f624ef43e19b4a2d700434401ae29bccf882d84`
- 运行镜像：`sha256:c98c7004a19274a7897ac267784cc376f9ad41e28570de28edfd57ecee5a9bd6`
- 运行边界：production deployment lock、`draft_only` runtime、固定账号与固定 2026-09-21 edition。

## 写入与回查

- 初始生产 plan 返回 `planned`、`images=5`、`completed_uploads=0`、`external_writes=0`。
- apply 仅形成五组 inline-image upload intent/ACK 和一组 `draft/add` intent/ACK；没有 `draft/update`、publish、mass-send、delete 或数据库业务写入。
- 首次 add 后，官方读回确认标题、作者、摘要、封面、评论设置、正文可见文字、链接、七图结构和图片顺序一致；第一/第七图保持，中间五图全部命中本批次已验收胸牌图。
- 微信把已发布正文根 `section` 上仅有的八项全局 style 声明移除并保存为 `style=""`。最终 verifier 只接受这一精确规范化：根节点、八项完整集合和空串结果必须完全匹配；任何其他字段、CSS、节点、文字、链接或图片差异均拒绝。目标测试 47/47 通过，独立检查通过。
- 最终官方 plan 返回 `readback_verified`、`external_writes=0`、`not_published=true`、`published_unchanged=true`，并通过 draft get 与 batchget 证明新草稿唯一。
- 写入本地 readback receipt 后连续两次 `create --apply` 均返回 `readback_verified` 和 `external_writes=0`，证明五次图片上传与一次 `draft/add` 未重放，没有第二篇草稿。

证据不记录 access token、media ID、article ID、正文、图片 URL 或其他 provider secret。
