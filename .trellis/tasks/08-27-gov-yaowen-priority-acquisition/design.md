# Design: 中国政府网要闻高优先级采集

## Source Boundary

新增 `china-government-news` 来源，入口固定为
`https://www.gov.cn/yaowen/liebiao/YAOWENLIEBIAO.json`，仅允许 `www.gov.cn` 和
`/yaowen/liebiao/`。它使用独立 `gov_cn_yaowen_v1` 连接器身份，底层复用现有政府 JSON
记录解析和 HTML 详情抽取。独立身份保证错误、fixture、版本回放和生产观察不与
`china-government-policy` 混淆。

```text
YAOWENLIEBIAO.json
  -> bounded JSON discovery
  -> www.gov.cn + /yaowen/liebiao/ allowlist
  -> detail .pages_content extraction
  -> science-tech-editorial-v3-broad
  -> relevant Tier-A candidate + immutable snapshot
  -> governance/event organization
```

## Priority Boundary

新增选题快照版本和组合式权威来源优先规则。优先认证来自持久化 source occurrence，
主题资格来自当前 editorial cohort，最终资格仍由硬否决、普通阈值或既有 Tier A/B
硬科技候选池决定。优先规则只改变 eligible 候选的分组顺序，不单独制造 eligibility
或新的阈值绕过。

```text
authenticated gov-yaowen occurrence
  AND current qualified science-tech cohort
  AND eligible under existing threshold/hard-tech-pool rules
  AND zero hard veto
    -> authoritative qualified priority group
```

现有教育部实质性科技教育优先语义保持有效，并与合格政府要闻共享受保护优先组。
LLM reranker 仍只能在同组内排序。历史 `.10` 继续使用原选择优先规则，只有新快照读取
新组合规则。

## Compatibility and Rollout

- 来源同步通过确定性 seed/version ID 新增一条记录，不覆盖现有政策来源。
- 连接器 fixture 固定包含一个合格硬科技要闻、一个普通政务要闻和一个站外 URL。
- 部署后先做入口和单详情 live smoke，再同步生产来源并执行定向补采；随后只观察正常
  治理和选题链路，不人工写 daily selection 或触发交付。
- 回滚时禁用/移除新 source seed 并恢复上一选题版本默认值；历史候选、快照和配置保留
  供审计，不需要删除数据。

## Risks

- 要闻 JSON 含央视等站外链接：主机和路径 allowlist 必须在 discovery 阶段丢弃。
- 权威来源可能包含大量非科技新闻：采集阶段的 v3 title/body 主题判断是必要门槛。
- 绝对来源优先可能压制更高质量普通来源：优先仅作用于已合格候选，最终在优先组内仍
  由 LLM 多维评分和确定性回退排序。
