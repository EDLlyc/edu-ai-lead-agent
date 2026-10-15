import { useEffect, useState } from "react";

import styles from "../Admin.module.css";
import pick from "./HeldPick.module.css";
import type { HeldPickApi, HeldPickReview, NewsPick } from "./api";

const HOOK_LIMIT = 120;

function splitTags(value: string): readonly string[] {
  return value.split(/\s+/).filter((tag) => tag !== "");
}

function deadlineCopy(iso: string): string {
  const clock = new Intl.DateTimeFormat("zh-CN", {
    timeZone: "Asia/Shanghai",
    hour: "2-digit",
    minute: "2-digit",
    hourCycle: "h23",
  }).format(new Date(iso));
  return `当天 ${clock} 前可推送，过时作废`;
}

type Status = {
  readonly kind: "idle" | "busy" | "error" | "done";
  readonly text: string;
};

function messageOf(error: unknown, fallback: string): string {
  return error instanceof Error && error.message !== ""
    ? error.message
    : fallback;
}

/**
 * Review, edit and push one held 人工加推. Only the hook sentence and the hashtags are editable;
 * the copy rules re-check them. A push needs two confirmations because it reaches the formal
 * parents' group and cannot be recalled.
 */
export function HeldPickEditor({
  candidateKey,
  api,
  onPushed,
  onSessionExpired,
}: {
  readonly candidateKey: string;
  readonly api: HeldPickApi;
  readonly onPushed: (pick: NewsPick) => void;
  readonly onSessionExpired: (error: unknown) => boolean;
}) {
  const [review, setReview] = useState<HeldPickReview | null>(null);
  const [hook, setHook] = useState("");
  const [tags, setTags] = useState("");
  const [checked, setChecked] = useState<HeldPickReview | null>(null);
  const [confirm, setConfirm] = useState<0 | 1 | 2>(0);
  const [pushed, setPushed] = useState(false);
  const [status, setStatus] = useState<Status>({
    kind: "busy",
    text: "正在读取待审核文案…",
  });

  useEffect(() => {
    let cancelled = false;
    api.loadReview(candidateKey).then(
      (loaded) => {
        if (cancelled) return;
        setReview(loaded);
        setHook(loaded.hook ?? "");
        setTags((loaded.hashtags ?? []).join(" "));
        setStatus({ kind: "idle", text: "" });
      },
      (error: unknown) => {
        if (cancelled || onSessionExpired(error)) return;
        setStatus({
          kind: "error",
          text: messageOf(error, "读取失败，请重试"),
        });
      },
    );
    return () => {
      cancelled = true;
    };
  }, [api, candidateKey, onSessionExpired]);

  if (review === null) {
    return (
      <p
        className={status.kind === "error" ? styles.error : styles.hint}
        role={status.kind === "error" ? "alert" : "status"}
      >
        {status.text}
      </p>
    );
  }

  const savedHook = review.hook ?? "";
  const savedTags = (review.hashtags ?? []).join(" ");
  const dirty =
    hook.trim() !== savedHook || splitTags(tags).join(" ") !== savedTags;
  const shown = checked ?? review;
  const issues = shown.issues ?? [];
  const errors = issues.filter((issue) => issue.severity === "error");
  const warnings = issues.filter((issue) => issue.severity === "warning");
  const editable = review.editable && !pushed;
  const savedHasError = (review.issues ?? []).some(
    (issue) => issue.severity === "error",
  );
  const busy = status.kind === "busy";
  const canPush = editable && !dirty && !savedHasError && !busy;

  const revise = async (dryRun: boolean) => {
    setStatus({ kind: "busy", text: dryRun ? "正在检查…" : "正在保存…" });
    setConfirm(0);
    try {
      const result = await api.revise(candidateKey, {
        hook: hook.trim(),
        hashtags: splitTags(tags),
        dryRun,
      });
      const resultIssues = result.issues ?? [];
      const problems = resultIssues.filter(
        (issue) => issue.severity === "error",
      ).length;
      const hints = resultIssues.length - problems;
      if (!dryRun && result.saved === true) {
        setReview(result);
        setHook(result.hook ?? "");
        setTags((result.hashtags ?? []).join(" "));
        setChecked(null);
        setStatus({
          kind: "idle",
          text: hints > 0 ? `已保存，有 ${hints} 条提醒` : "已保存",
        });
        return;
      }
      setChecked(result);
      setStatus(
        problems > 0
          ? {
              kind: "error",
              text: `有 ${problems} 条规则不通过，${dryRun ? "需要修改" : "没有保存"}`,
            }
          : {
              kind: "idle",
              text: hints > 0 ? `检查通过，有 ${hints} 条提醒` : "检查通过",
            },
      );
    } catch (error) {
      if (onSessionExpired(error)) return;
      setStatus({ kind: "error", text: messageOf(error, "提交失败，请重试") });
    }
  };

  const push = async () => {
    setStatus({ kind: "busy", text: "正在推送到正式群…" });
    try {
      const result = await api.push(candidateKey);
      setPushed(true);
      setConfirm(0);
      setStatus({
        kind: "done",
        text: "已推送到正式家长群，长图会在几分钟后自动补发",
      });
      onPushed(result);
    } catch (error) {
      setConfirm(0);
      if (onSessionExpired(error)) return;
      setStatus({ kind: "error", text: messageOf(error, "推送失败，请重试") });
    }
  };

  return (
    <div className={pick.editor} role="group" aria-label="审核加推文案">
      <p className={styles.hint}>{deadlineCopy(review.push_deadline)}</p>
      <div className={pick.copy}>
        <p className={pick.fixed} title="系统按原文生成，不能改">
          {review.heading}
        </p>
        {(review.headline ?? []).map((line) => (
          <p className={pick.fixed} title="新闻原标题，不能改" key={line}>
            {line}
          </p>
        ))}
        <label className={styles.field}>
          <span>引导语（可改）</span>
          <textarea
            value={hook}
            maxLength={HOOK_LIMIT}
            rows={2}
            disabled={!editable || busy}
            onChange={(event) => {
              setHook(event.target.value);
              setChecked(null);
            }}
          />
        </label>
        <p className={pick.fixed}>{review.source_line}</p>
        <p className={pick.fixed}>{review.link_line}</p>
        <label className={styles.field}>
          <span>话题标签（可改，空格分隔，最多 3 个）</span>
          <input
            value={tags}
            disabled={!editable || busy}
            placeholder="#赛先生科学 #科学思维"
            onChange={(event) => {
              setTags(event.target.value);
              setChecked(null);
            }}
          />
        </label>
      </div>
      {issues.length === 0 ? null : (
        <ul className={pick.issues} aria-label="规则检查结果">
          {[...errors, ...warnings].map((issue) => (
            <li
              data-severity={issue.severity}
              key={`${issue.code}-${issue.message}`}
            >
              <strong>{issue.severity === "error" ? "不通过" : "提醒"}</strong>{" "}
              {issue.message}
            </li>
          ))}
        </ul>
      )}
      {!editable ? null : confirm === 0 ? (
        <span className={styles.rowActions}>
          <button
            type="button"
            disabled={busy}
            onClick={() => {
              void revise(true);
            }}
          >
            检查文案
          </button>
          <button
            type="button"
            disabled={!dirty || busy}
            onClick={() => {
              void revise(false);
            }}
          >
            保存修改
          </button>
          <button
            type="button"
            className={styles.primary}
            disabled={!canPush}
            title={
              dirty
                ? "先保存修改再推送"
                : savedHasError
                  ? "文案有不通过的规则"
                  : undefined
            }
            onClick={() => setConfirm(1)}
          >
            推送到正式群
          </button>
        </span>
      ) : confirm === 1 ? (
        <div className={pick.confirm} role="group" aria-label="确认推送">
          <p>将推送下面这条文案和配图到正式家长群：</p>
          <pre className={pick.preview}>{review.copywriting}</pre>
          <span className={styles.rowActions}>
            <button
              type="button"
              className={styles.primary}
              onClick={() => setConfirm(2)}
            >
              确认推送
            </button>
            <button type="button" onClick={() => setConfirm(0)}>
              取消
            </button>
          </span>
        </div>
      ) : (
        <div
          className={`${pick.confirm} ${pick.final}`}
          role="alertdialog"
          aria-label="再次确认推送"
        >
          <p>
            <strong>再次确认：</strong>
            发到正式家长群后不能撤回，长图会在几分钟后自动补发。
          </p>
          <span className={styles.rowActions}>
            <button
              type="button"
              className={styles.primary}
              disabled={busy}
              onClick={() => {
                void push();
              }}
            >
              确认发送
            </button>
            <button type="button" disabled={busy} onClick={() => setConfirm(0)}>
              返回
            </button>
          </span>
        </div>
      )}
      <p
        className={status.kind === "error" ? styles.error : styles.hint}
        role="status"
        aria-live="polite"
        data-kind={status.kind}
      >
        {status.text ||
          (!editable
            ? ""
            : dirty
              ? "有未保存的修改：先检查、保存，再推送"
              : "可以直接推送，或先修改引导语和标签")}
      </p>
    </div>
  );
}
