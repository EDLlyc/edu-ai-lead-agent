# 采集：一页读不出来，不再拖垮整个新闻源

给后来改采集的人。后台「新闻源」里“最近抓取”显示失败时，先看这份。

## 现在的行为

采集一个新闻源时，会逐篇打开文章页。以前只要有一页读不出标题或正文（正文少于 80 字），
整个任务就记为失败 `parse_failure`，这个源这一轮一篇都进不来。

现在：

- 读不出的那一页**跳过**，在 `source_observations` 记一条 `parse_failure`
  （`metadata` 里有 `reason` 和截短的 `url`），日志是 `acquisition_item_parse_skipped`。其他页照常入库。
- 只有**这一轮尝试过的每一页都读不出来**，整个任务才失败。这样网站真的改版时，问题还是会暴露出来，
  而不是安静地什么都抓不到。
- 后台把失败码翻成中文：`parse_failure` 显示“没有一页能读出正文”，`http_*` 显示“网站返回 N”。
  对应表在 `frontend/src/features/admin/sources/labels.ts` 的 `FAILURE_LABELS`。

## 代码在哪

| 文件 | 作用 |
|---|---|
| `backend/app/application/services/execute_acquisition.py` | `detail_attempt_count` / `parse_skipped_count`，跳过和“全部失败才报错” |
| `backend/app/infrastructure/ingestion/connectors.py`（`HtmlConnector.extract`） | 标题缺失或正文不足时抛 `ParseError`（`parse_failure`） |
| `backend/tests/integration/test_title_relevance_ingestion.py` | `_BrokenPagesFetcher`，两条测试：部分页坏仍入库；全部页坏才失败 |
| `frontend/src/features/admin/sources/labels.ts` | 失败码到中文，`latestJobLabel` 用它 |

## 为什么还会有很多读不出的页

自己加的源（`generic_html_v1`）如果“链接包含”是空的，会用 `looks_like_article_path` 猜哪些链接是文章，
所以栏目页、旧公告也会被打开。读不出就被跳过，但还是浪费请求。给每个自加源填上“链接包含”
（例如文章路径里固定出现的片段），比改代码有效。

## 怎么查一个源

```sql
-- 最近的任务
select status, outcome, error_code, new_count, filtered_count, completed_at
from acquisition_jobs where source_id = '<source uuid>' order by created_at desc limit 5;

-- 被跳过的页面
select o.error_code, o.metadata->>'reason', o.metadata->>'url', o.observed_at
from source_observations o join acquisition_jobs j on j.id = o.job_id
where j.source_id = '<source uuid>' and o.outcome = 'parse_failure'
order by o.observed_at desc limit 20;
```

生产库用只读账号查，见 `scripts/ops/README.md`。

## 部署上要注意

只有 `acquisition-worker` 用到这段代码。别用普通 `compose up`：它会重新读 `.env`，改掉这个容器创建时的
`CONTENT_SCORING_VERSION`。做法见 `.trellis/spec/guides/production-mainline.md` 的
“Live since 2026-10-16”和 `.trellis/tasks/10-15-public-hosting/overlay-acquisition-skip/activate.sh`。
