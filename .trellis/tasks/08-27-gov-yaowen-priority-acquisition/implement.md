# Implementation Plan: 中国政府网要闻高优先级采集

1. 增加 `china-government-news` Tier-A source seed 和独立 `gov_cn_yaowen_v1` connector key，复用政府 JSON/详情抽取逻辑并收紧要闻路径。
2. 增加要闻列表与详情 fixture，扩展 connector、URL policy、source sync、API/source-count 和采集相关性测试。
3. 增加新的权威要闻 topic priority policy 与当前 scoring snapshot；只对真实 occurrence、合格 cohort、既有 eligible 且无硬否决事件应用，并保持历史配置回放。
4. 扩展 topic-selection 单元和 PostgreSQL repository 测试，覆盖合格优先、普通政务不优先、硬否决/不 eligible 不优先以及 LLM 不跨 priority group。
5. 更新 acquisition、topic-selection、database 和 quality specs 中的活跃来源数量、连接器身份、优先边界和生产验证契约。
6. 运行 scoped Ruff/mypy/pytest、connector/live-smoke、backend quality gates；对公开要闻入口做一条列表 + 一条详情的无落盘 live smoke。
7. 提交并部署相关变更；在生产同步新来源，执行定向补采并只读确认目标文章的 candidate、snapshot、governance lineage 和选题资格，不人工强制发布。

## Validation

```bash
cd backend
pytest -q --no-cov \
  tests/contract/test_source_connectors.py \
  tests/unit/test_editorial_relevance.py \
  tests/unit/test_topic_selection.py \
  tests/integration/test_acquisition_repositories.py \
  tests/integration/test_title_relevance_ingestion.py \
  tests/integration/test_topic_selection_repositories.py
ruff check app tests
mypy app
```

## Risky Files and Rollback

- `source_profiles.py` and connector registry affect scheduled job count; any live parse or safety failure blocks activation.
- `topic_selection.py` is already modified by another in-progress task; implementation must preserve those edits and make a minimal additive new snapshot/policy change.
- `.trellis/spec/backend/agent-pipeline.md` and `topic-selection.md` are also dirty; update only the owning paragraphs without replacing concurrent work.
- Production rollback restores the prior image/commit and previous current scoring version; no destructive database cleanup is required.
