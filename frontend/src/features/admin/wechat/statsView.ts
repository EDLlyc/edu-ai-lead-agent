import type { DailyStats, WeChatStats } from "./api";

export interface StatsDay {
  readonly date: string;
  readonly values: DailyStats | null;
}

// These are business-date labels from the server, not instants in the browser's timezone.
export function shiftDate(day: string, offset: number): string {
  const parsed = new Date(`${day}T00:00:00Z`);
  parsed.setUTCDate(parsed.getUTCDate() + offset);
  return parsed.toISOString().slice(0, 10);
}

export function statsDays(stats: WeChatStats): readonly StatsDay[] {
  const rows = new Map(stats.daily.map((row) => [row.date, row]));
  const missing = new Set(stats.missing_dates);
  const result: StatsDay[] = [];
  for (
    let day = stats.range_start;
    day <= stats.range_end;
    day = shiftDate(day, 1)
  ) {
    result.push({
      date: day,
      values: missing.has(day) ? null : (rows.get(day) ?? null),
    });
  }
  return result;
}

export function statsTotal(
  days: readonly StatsDay[],
  key: keyof Omit<DailyStats, "date">,
): string {
  const known = days.flatMap((day) =>
    day.values === null ? [] : [day.values],
  );
  if (known.length === 0) return "—";
  const total = known.reduce((sum, row) => sum + row[key], 0);
  const missing = days.length - known.length;
  return missing === 0 ? String(total) : `已知 ${total}（缺 ${missing} 天）`;
}
