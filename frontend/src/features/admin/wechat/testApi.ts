import { vi } from "vitest";

import type { PublishJob, WeChatAccount, WeChatApi, WeChatDraft } from "./api";

export const ACCOUNT: WeChatAccount = {
  id: "00000000-0000-0000-0000-0000000000a1",
  name: "赛先生",
  app_id: "wx0123456789abcdef",
  secret_hint: "••••cdef",
  topics: ["科学", "教育"],
  enabled: true,
  last_verified_at: "2026-10-09T01:00:00Z",
  last_verify_error: null,
  created_by: "liyuchen",
  created_at: "2026-10-09T01:00:00Z",
};

export const DRAFT: WeChatDraft = {
  media_id: "M1",
  updated_at: "2026-10-08T02:00:00Z",
  articles: [
    { title: "科学营开营", author: "小赛", digest: "孩子们走进实验室" },
  ],
  open_job_id: null,
};

export function job(changes: Partial<PublishJob> = {}): PublishJob {
  return {
    id: "00000000-0000-0000-0000-0000000000b1",
    account_id: ACCOUNT.id,
    account_name: ACCOUNT.name,
    media_id: "M1",
    title: "科学营开营",
    scheduled_at: "2026-10-09T02:00:00Z",
    status: "publishing",
    article_url: null,
    error: null,
    created_by: "liyuchen",
    cancelled_by: null,
    created_at: "2026-10-09T02:00:00Z",
    completed_at: null,
    ...changes,
  };
}

export function fakeWeChatApi(overrides: Partial<WeChatApi> = {}) {
  return {
    status: vi.fn(() => Promise.resolve({ secretKeyConfigured: true })),
    accounts: vi.fn(() => Promise.resolve<readonly WeChatAccount[]>([ACCOUNT])),
    options: vi.fn(() =>
      Promise.resolve([
        { id: ACCOUNT.id, name: ACCOUNT.name, topics: ACCOUNT.topics },
      ]),
    ),
    bind: vi.fn(() => Promise.resolve(ACCOUNT)),
    update: vi.fn(() => Promise.resolve(ACCOUNT)),
    verify: vi.fn(() => Promise.resolve(ACCOUNT)),
    drafts: vi.fn(() => Promise.resolve({ total: 1, items: [DRAFT] })),
    published: vi.fn(() =>
      Promise.resolve({
        total: 1,
        items: [
          {
            article_id: "A1",
            updated_at: "2026-09-29T02:34:00Z",
            articles: [
              { title: "已发布的一篇", url: "https://mp.weixin.qq.com/s/a1" },
            ],
          },
        ],
      }),
    ),
    jobs: vi.fn(() => Promise.resolve<readonly PublishJob[]>([])),
    publish: vi.fn(() => Promise.resolve(job())),
    cancel: vi.fn(() => Promise.resolve(job({ status: "cancelled" }))),
    ...overrides,
  } satisfies WeChatApi;
}
