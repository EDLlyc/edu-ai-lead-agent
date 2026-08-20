# 扩展硬科技新闻检索与航天突破覆盖

## Goal

把当前偏严的硬科技筛选改为“宽召回、后排序”：只要受控来源中的新闻具有明确硬科技主题，计划试验、冲刺目标、失败复盘、融资、发布会、普通产品发布和已完成突破都可以形成候选并进入有界 LLM 排序；不同内容通过确定性类别、分数、风险和原因码体现优先级，而不是在采集阶段直接删除。来源真实性、事实治理、时效、重复、隐私法律安全和历史规则回放边界继续保留。

## Background and confirmed facts

- 当前正式启用的 10 个来源中已经包含两个新华网来源：
  - `xinhua-tech` / 新华网科技，Tier B，入口 `https://www.news.cn/tech/`；
  - `xinhua-education` / 新华教育，Tier B，入口 `https://education.news.cn/index.htm`。
- 新华网科技在 2026-08-19 09:11 发布《朱雀三号遥二运载火箭发射成功 一子级成功着陆预定位置》，正文确认火箭一子级成功着陆于回收场预定位置。
- `xinhua_tech_v1` 已允许并解析 `/c.html` 文章；该新闻位于新华网科技入口页，因此本次不需要新增来源或放宽域名、路径范围。
- 当前 `science-tech-editorial-v2` 能识别“火箭/航天”主题，但不把“成功着陆、成功回收、完成陆上垂直回收”识别为实质进展。上述新华网标题和两个同义标题当前都稳定返回 `missing_substantive_frontier_progress`。
- 现有 `science-tech-editorial-v2` 采用“主题 + 实质进展”双条件，并把融资、市场、发布会和普通公司产品发布作为排除项；这一边界与用户现在要求的宽召回不一致。
- 当前 topic scoring 还要求候选总分达到 `0.59`。硬科技突破通常没有教育产品矩阵匹配，可能在 acquisition 合格后仍低于阈值；LLM rerank 只处理已经 eligible 的候选，不能补救这一层淘汰。

## Requirements

### R1 — 硬科技主题宽召回

- 新规则只要求存在明确的受控硬科技主题，不再要求同时命中“已完成突破”词。
- 主题范围沿用并完善现有人工智能、机器人/具身智能、航空航天/商业航天、量子、物理/生命科学、新材料、超导、新能源/核聚变等受控类别。
- 航天中文至少补充“运载火箭、可回收/可重复使用火箭、火箭一级/一子级、垂直回收/着陆、陆上/海上回收”等稳定表达；英文补充 reusable launch vehicle/rocket、booster landing/recovery 等表达。
- “成功着陆/回收”和“重大突破”仍获得更高进展分，但不再是成为候选的前提。

### R2 — 允许多种硬科技新闻形态

- 计划试验、冲刺目标、试验/回收失败、融资、市场动态、发布会和普通产品发布，只要明确属于硬科技主题，都可以形成候选并进入 LLM 排序池。
- 上述形态必须保留稳定的内容类别、匹配项、风险/营销信号和原因码，供确定性排序与 LLM 解释使用；不得伪装成“已完成突破”。
- 与硬科技无关的普通财经、消费、娱乐、生活、教育营销等内容仍不进入。
- 未核验传闻、无合格证据、隐私/法律安全不确定、陈旧或近期已成功推送的重复事件继续受现有 hard veto 约束。
- 不增加任意网页搜索，不新增未审来源，不扩大新华网允许主机或路径。

### R3 — 不可变版本与历史回放

- 不得原地改变 `science-tech-editorial-v2` 的语义；新增当前规则版本并保留 v2 精确行为。
- 当前 acquisition/source-version 身份必须升级；已有 source-version 和历史 acquisition 仍可按 v2 回放。
- 新增当前 topic-scoring 版本以绑定新规则；`.6`、`.7`、`.8` 的快照继续绑定 v2，阈值、delivered-history 重复规则、教育优先和 LLM rerank 边界不被重解释。
- 当前默认阈值继续为 `0.59`；本任务不调整选题权重、重复窗口或 LLM 排序策略。

### R4 — 可审计采集与选题

- 标题阶段应将已完成的火箭回收里程碑排在 neutral probe 之前，正文阶段再次确认。
- 候选和选题解释继续记录规则版本、cohort、进展匹配项与 reason codes。
- 新华网科技与新华教育继续保持 Tier B；正式源总数继续为 10。

### R5 — 宽候选池而非全局改分

- 已由受控 Tier A/B 来源支持、具有明确硬科技主题、完成事实治理且没有任何 hard veto 的候选，都应能够进入后续 LLM 排序池，即使其总分低于 `0.59`。
- 此放宽必须是版本化、可审计的“硬科技候选池”政策，不得改写历史 `.6`/`.7`/`.8`，不得把全局数值阈值从 `0.59` 再次下调。
- LLM 只能在这一受控候选池内排序，不能移除 veto、虚构事实或把 out-of-scope 内容提升为 eligible。

## Acceptance Criteria

- [x] 新华网 2026-08-19 的准确标题被新规则识别为 `frontier_science_technology`，且匹配稳定的航天主题与回收/着陆进展原因。
- [x] “我国可重复使用火箭一子级成功回收”“新一代商业火箭完成陆上垂直回收”以及对应英文完成态样本被接受并获得高进展信号。
- [x] “朱雀三号拟再次开展回收试验”“火箭一级回收失败”“商业航天企业完成融资”“机器人新品发布会举行”都成为硬科技候选，但分别保留 planned/failed/industry-capital/event-or-product 等可审计信号，不冒充成功突破。
- [x] “普通消费品促销”“非科技企业融资”“明星发布会”“无硬科技主题的市场规模报道”仍保持 out of scope。
- [x] `xinhua-tech` 的受控 connector fixture 证明该类 `/tech/YYYYMMDD/<id>/c.html` 标题可被发现和解析；不新增来源或主机。
- [x] 新 acquisition 跑次会优先探测该里程碑并持久化新规则版本；neutral、排除和 freshness 计数仍可审计。
- [x] 历史 v2 规则和 `.6`/`.7`/`.8` scoring metadata 精确不变；新默认 scoring 版本绑定新规则、`0.59` 阈值和既有 delivered-history veto。
- [x] 新默认策略下，来源合格、治理完成、无 veto 的各种硬科技新闻形态均可进入 LLM 排序池；传闻、无证据、陈旧、重复、隐私法律风险等真实 veto 仍不可进入。
- [x] 相关 domain、connector、acquisition integration、topic-selection replay/config tests 通过；完整后端质量门通过。

## Out of Scope

- 新增新闻网站、开放式搜索引擎、任意 URL 或爬虫范围扩张。
- 修改新闻评分权重、`0.59` 阈值、7 天重复窗口、LLM rerank 或发布策略。
- 手工补采、重放、推送、部署或修改生产服务器配置。
- 把计划、失败、融资、活动或产品发布错误标注为“重大突破”；它们可以进入，但必须保留真实类别。

## Evidence

- 任务研究：[`research/xinhua-aerospace-gap.md`](./research/xinhua-aerospace-gap.md)
- 当前来源：`backend/app/infrastructure/ingestion/source_profiles.py`
- 当前 connector：`backend/app/infrastructure/ingestion/connectors.py`
- 当前规则：`backend/app/domain/editorial_relevance.py`
