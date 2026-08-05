# 教育部科学新闻 Top 1 优先级

## Goal

在现有权威新闻采集、事实治理和每日选题链路中增加教育部官方新闻源。当天存在合规、新鲜、完成治理且与科学/科技相关的教育部新闻时，将它确定为当天 Top 1，并沿用现有文案、品牌 IP 生图、验证、审计和版本化素材包链路。

## User value

让每日选题优先反映教育主管部门发布的科学教育、科技、人工智能和机器人等权威信号，同时保留十天新鲜度、证据绑定、人工复核边界、幂等和不自动发布约束。

## Background and confirmed facts

- 采集注册表位于 [`backend/app/infrastructure/ingestion/source_profiles.py`](../../../backend/app/infrastructure/ingestion/source_profiles.py)，当前有八个版本化来源；采集任务通过 `connector_key` 选择连接器。
- [`SafeHttpFetcher`](../../../backend/app/infrastructure/ingestion/fetcher.py) 当前强制 HTTPS，并对每个重定向跳、公共 DNS、host/path allowlist、响应大小、内容类型、限速和重试执行安全校验；它不绕过验证码、登录、付费墙或反爬挑战。
- 当前采集新鲜度边界为十天；发布日期未知的文章可以被详情解析尝试，但不会进入正常候选池。
- 事实治理和选题阶段消费已保存的快照与投影，不应再次访问原站。选题硬 veto 独立于数值评分，当前日选题支持不可变的同日 revision。
- 选题完成后，现有 content worker 已负责文案、品牌相关图片、验证/审计和素材包；本任务不创建第二条下游链路。
- 2026-08-05 对 `https://www.moe.gov.cn/jyb_xwfb/` 的生产安全探测显示：HTTPS 入口 302 到同 host/path 的 HTTP，HTTP 页面返回 200、约 64 KB HTML；页面包含最新工作动态和文章 `教育部部署开展义务教育阶段科学教育“做中学”领航行动`。
- 该页面的列表文章路径和详情页结构可由固定选择器解析：列表工作动态区域 `#one_con1`，详情正文 `.TRS_Editor`，详情元数据 `ArticleTitle`、`PubDate` 和 `publishdate`。

## Requirements

### R1. 受控教育部官方来源

- 增加一个 Tier A、版本化、可幂等 seed 的教育部新闻源：
  - entry URL：`https://www.moe.gov.cn/jyb_xwfb/`
  - allowed host：`www.moe.gov.cn`
  - allowed path prefix：`/jyb_xwfb/`
  - 专用 connector 和 parser 版本
  - `moe-science-v1` 相关性规则
  - `moe-science-top1-v1` 选题优先级策略
- 只对这个 source version 开启严格的 HTTP fallback。允许范围仍由精确 host/path allowlist、公共 DNS、响应大小、内容类型、限速、robots/条款记录和重定向上限约束；默认及其他来源继续只允许 HTTPS。
- 不增加任意 URL 搜索、代理轮换、User-Agent 轮换、浏览器隐身、验证码破解、登录自动化或其他反爬绕过。
- 所有源状态、快照、观察、解析失败、策略拒绝和新鲜度过滤原因都必须可审计。

### R2. 科学相关性规则

- `moe-science-v1` 使用固定、可版本化的宽口径词表，覆盖科学、科技、科创、人工智能、机器人、天文、航天、物理、化学、生物、实验、科普、探究等主题。
- 规则对标题和有界详情正文共同判断；正文参与匹配的字符数必须有上限，命中标题词、正文词、规则版本和截断信息都要保存。
- 采集只在配置的扫描和详情探测上限内工作：先按标题命中优先，再用固定数量的标题未命中项目填充详情探测窗口；不因找不到命中而扩大到无限抓取。
- 十天内、日期已知且命中规则的文章才进入正常 evidence candidate 池。旧文章、日期未知、非科学文章、越权 URL 和策略不允许的文章不能进入候选池，并记录安全原因。
- 现有 `ai-title-v1` 及其他来源的相关性行为保持不变。

### R3. 教育部科学新闻硬 Top 1

- 只有同时通过现有 freshness、治理完成、证据绑定、Tier A/B、来源安全和所有 hard veto 的教育部科学候选才有资格触发优先级。
- 资格成立后，教育部科学候选的排序组高于所有普通 eligible 候选，与普通候选的数值总分无关。
- 多个教育部科学候选之间沿用已有确定性顺序：数值分、来源信任、事件时间、稳定事件 ID。
- 教育部候选被 veto、过期、治理未完成、证据不合格或不存在时，不得强行 Top 1；原有评分和 `no_topic` 行为保持不变。
- 选题分数的解释中持久化来源策略、是否实际应用优先级和原因，并通过选题 API 暴露给操作人员。

### R4. 下游交接与幂等

- 选中的事件继续进入既有每日主题 revision、文案生成、品牌 IP 参考图选择、生图、验证、审计和素材包状态机，不增加特殊重复 job。
- 重复调度、worker 重启和同日重算只能通过现有不可变 revision/幂等机制收敛，不直接修改数据库中的旧锁定结果。
- 同日已有可恢复的 `no_topic`/`all_vetoed` 时，后续更晚治理 cutoff 按现有 revision 机制重新计算；已经锁定的正常 selected 结果不被静默覆盖。
- 不自动发布到朋友圈、企业微信或其他社交平台。

## Acceptance criteria

- [ ] 教育部 source seed、source version、HTTP fallback 配置和专用 connector 可幂等创建；迁移、source API 和九来源相关测试通过。
- [ ] 教育部列表/详情 fixture 能发现和提取当前文章，固定 host/path、HTTP fallback、重定向、公网 DNS、响应上限和 parser drift 测试通过。
- [ ] 科学标题命中、正文命中、标题与正文均不命中、十天边界、未知日期、旧文章、越权 URL 和策略拒绝均有确定性测试；候选和 observation 保存规则版本、命中词和过滤原因。
- [ ] 一个合规教育部科学事件与一个分数更高的普通事件并存时，教育部事件为 rank/Top 1；API 解释显示 `moe-science-top1-v1` 优先级已应用。
- [ ] 教育部候选出现任意现有 hard veto 时不被选中；没有教育部候选时，现有评分、排序、veto 和 `no_topic` 测试保持通过。
- [ ] 同日可恢复 `all_vetoed` 运行在新治理 cutoff 下生成不可变 revision，并只向下游交接一次；重放不产生重复文案、图片或素材包。
- [ ] 教育部真实小范围抓取只访问明确 allowlist 内的入口和详情，记录 run/job/title/URL/过滤结果；live smoke 失败时保持安全失败而不是放宽策略。
- [ ] `make backend-check`、`make frontend-check`、`make api-contract-check`、`docker compose config -q`、`make doctor` 和 `git diff --check` 通过。

## Out of scope

- 全网搜索、动态浏览器抓取、代理池、验证码或登录绕过、隐身反爬和社交平台自动发布。
- 通过模型自由判断 URL 或直接用模型替代确定性相关性/安全规则。
- 修改已锁定的 daily topic 行、删除旧 revision 或绕过 governance/evidence veto。
- 为教育部来源新建独立文案、生图或企业微信分发流程。

## Key decisions and risks

- 已确认采用宽口径 `moe-science-v1`，因为用户希望覆盖科学、科创、AI、机器人等教育相关主题；泛教育政策标题若没有科学/科技信号仍排除。
- 已授权仅对 `www.moe.gov.cn/jyb_xwfb/` 这一个精确来源启用 HTTP fallback。风险是该源的 fallback 传输不具备 TLS 保密性；通过 source version、精确 allowlist、公网 DNS、响应限制、限速和无进一步越权重定向控制风险，绝不扩大为全局 HTTP。
- 现有 source seed 增加版本化字段后，重新 seed 可能为旧来源生成新的不可变 source version；旧版本和历史快照保留，active version 只切换到经过测试的新版本。
- 现场 live HTML 是动态外部状态；fixture/契约测试是主验收依据，live smoke 只作上线前探测，解析漂移时保留 typed failure。

## Planning status

- Blocking product and security decisions: resolved.
- `design.md`: ready for review.
- `implement.md`: ready for review.
- `implement.jsonl` / `check.jsonl`: curated with project specifications and source research.
- Product code has not been changed by this task; implementation awaits explicit approval of this planning summary.
