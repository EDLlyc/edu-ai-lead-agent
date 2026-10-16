import type { AdminSource, PreviewSample } from "./api";

export const ORGANIZATION_LABELS: Readonly<Record<string, string>> = {
  government: "政府",
  education_institution: "教育机构",
  research_organization: "科研机构",
  authoritative_media: "权威媒体",
};

export const TIER_LABELS = { A: "A 权威", B: "B 可信" } as const;

const timeFormat = new Intl.DateTimeFormat("zh-CN", {
  timeZone: "Asia/Shanghai",
  month: "2-digit",
  day: "2-digit",
  hour: "2-digit",
  minute: "2-digit",
  hourCycle: "h23",
});

const dateFormat = new Intl.DateTimeFormat("zh-CN", {
  timeZone: "Asia/Shanghai",
  year: "numeric",
  month: "2-digit",
  day: "2-digit",
});

export function formatTime(iso: string): string {
  return timeFormat.format(new Date(iso));
}

export function formatDate(iso: string | null): string {
  return iso === null ? "没有日期" : dateFormat.format(new Date(iso));
}

export function kindLabel(source: AdminSource): string {
  if (source.kind === "rss") return "RSS";
  if (source.kind === "html") return "网页";
  return "内置";
}

const FAILURE_LABELS: Readonly<Record<string, string>> = {
  parse_failure: "没有一页能读出正文",
  network_failure: "连不上网站",
  total_timeout: "网站响应太慢",
  response_too_large: "页面太大",
  unsupported_content: "不是网页或 RSS",
  dns_resolution_failed: "域名解析不到",
};

function failureText(code: string): string {
  if (code.startsWith("http_")) return `网站返回 ${code.slice(5)}`;
  return FAILURE_LABELS[code] ?? code;
}

/** One line for the 最近一次抓取 column. */
export function latestJobLabel(source: AdminSource): string {
  const job = source.latest_job;
  if (job === null) return "还没抓过";
  const when =
    job.completed_at === null ? "" : `${formatTime(job.completed_at)} · `;
  if (job.status === "failed") {
    return `${when}失败${job.error_code === null ? "" : `（${failureText(job.error_code)}）`}`;
  }
  return `${when}新增 ${job.new_count} · 过滤 ${job.filtered_count}`;
}

/** Whether acquisition would keep a previewed article, in the operator's words. */
export function sampleVerdict(sample: PreviewSample): {
  readonly kept: boolean;
  readonly text: string;
} {
  if (sample.problem !== null) return { kept: false, text: sample.problem };
  // Acquisition drops an article whose date it cannot read, like a stale one.
  if (sample.freshness === "unknown") {
    return { kept: false, text: "没识别到发布日期，不会收录" };
  }
  if (sample.freshness === "stale") {
    return { kept: false, text: "日期太旧，不会收录" };
  }
  if (!sample.relevant)
    return { kept: false, text: "和科技/教育无关，不会收录" };
  const topic = sample.topic === "education" ? "科技教育" : "前沿科技";
  return { kept: true, text: `${topic}，会收录` };
}
