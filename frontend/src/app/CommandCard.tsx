import { useState } from "react";

import styles from "./CommandCard.module.css";

type CommandCardProps = {
  readonly index: string;
  readonly title: string;
  readonly description: string;
  readonly command: string;
};

type CopyState = "idle" | "copied" | "failed";

export function CommandCard({
  index,
  title,
  description,
  command,
}: CommandCardProps) {
  const [copyState, setCopyState] = useState<CopyState>("idle");

  async function copyCommand(): Promise<void> {
    if (navigator.clipboard === undefined) {
      setCopyState("failed");
      return;
    }

    try {
      await navigator.clipboard.writeText(command);
      setCopyState("copied");
    } catch {
      setCopyState("failed");
    }
  }

  const feedback =
    copyState === "copied"
      ? `已复制：${command}`
      : copyState === "failed"
        ? "复制失败，请手动选择命令。"
        : "";

  return (
    <article className={styles.card}>
      <div className={styles.marker} aria-hidden="true">
        {index}
      </div>
      <div className={styles.content}>
        <h3>{title}</h3>
        <p>{description}</p>
        <div className={styles.commandRow}>
          <code>{command}</code>
          <button type="button" onClick={() => void copyCommand()}>
            {copyState === "copied" ? "已复制" : "复制"}
          </button>
        </div>
        <p className={styles.feedback} role="status" aria-live="polite">
          {feedback}
        </p>
      </div>
    </article>
  );
}
