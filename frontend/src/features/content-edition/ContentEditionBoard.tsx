import { useState } from "react";

import {
  currentShanghaiBusinessDate,
  type ContentEditionSelectionViewModel,
  type ContentEditionSlotViewModel,
} from "./api";
import { useContentEdition } from "./hooks";
import styles from "./ContentEditionBoard.module.css";

export function ContentEditionBoard() {
  const [businessDate, setBusinessDate] = useState(currentShanghaiBusinessDate);
  const edition = useContentEdition(businessDate);

  return (
    <section className={styles.board} aria-labelledby="content-edition-title">
      <div className={styles.heading}>
        <div>
          <p>THREE EDITIONS / ZERO TO THREE STORIES</p>
          <h2 id="content-edition-title">三时段内容版面</h2>
        </div>
        <form
          className={styles.dateControl}
          onSubmit={(event) => event.preventDefault()}
        >
          <label htmlFor="content-edition-date">业务日期（上海时区）</label>
          <input
            id="content-edition-date"
            type="date"
            value={businessDate}
            onChange={(event) => setBusinessDate(event.target.value)}
          />
        </form>
      </div>

      <p className={styles.guardrail}>
        每条新闻独立生产文案、图片与素材包；栏目不足时保持空位，不降低质量门槛。
      </p>

      {edition.isPending ? (
        <p className={styles.notice} role="status">
          正在读取早、中、晚栏目状态…
        </p>
      ) : null}
      {edition.isError ? (
        <p className={styles.notice} role="alert">
          三时段版面暂时不可用，请确认 API 服务状态。
        </p>
      ) : null}
      {edition.data !== undefined ? (
        <>
          {!edition.data.slotModeEnabled ? (
            <p className={styles.notice} role="status">
              三时段模式当前关闭；现有每日 Top 1 流程保持不变。
            </p>
          ) : null}
          <div
            className={styles.slotGrid}
            aria-label={`${edition.data.businessDate} 三时段栏目`}
            aria-live="polite"
          >
            {edition.data.slots.map((slot, index) => (
              <SlotColumn key={slot.slot} slot={slot} index={index + 1} />
            ))}
          </div>
        </>
      ) : null}
    </section>
  );
}

function SlotColumn({
  slot,
  index,
}: Readonly<{ slot: ContentEditionSlotViewModel; index: number }>) {
  return (
    <article className={styles.slot} data-state={slot.state}>
      <header className={styles.slotHeader}>
        <span className={styles.slotIndex}>0{index}</span>
        <div>
          <p>{slot.targetLabel} TARGET</p>
          <h3>{slot.displayName}</h3>
        </div>
        <span className={styles.stateBadge}>{slot.stateLabel}</span>
      </header>
      <dl className={styles.slotMeta}>
        <div>
          <dt>投递窗口</dt>
          <dd>{slot.windowLabel}</dd>
        </div>
        <div>
          <dt>独立选题</dt>
          <dd>
            {slot.selectedCount} / {slot.itemLimit}
          </dd>
        </div>
      </dl>

      <div className={styles.storyStack}>
        {slot.selections.map((selection) => (
          <StoryCard key={selection.id} selection={selection} />
        ))}
        {slot.selections.length === 0 ? (
          <div className={styles.emptyState}>
            <strong>
              {slot.enabled ? "本栏目暂无独立素材" : "栏目未启用"}
            </strong>
            <p>
              {slot.enabled
                ? "系统会展示准备、空栏目或窗口结束状态。"
                : "启用开关保持关闭，不会产生采集或投递任务。"}
            </p>
          </div>
        ) : null}
      </div>

      {slot.unfilledCount > 0 ? (
        <div
          className={styles.unfilled}
          aria-label={`${slot.displayName}栏目空位原因`}
        >
          <strong>保留 {slot.unfilledCount} 个空位</strong>
          <ul>
            {slot.unfilledReasons.map((reason) => (
              <li key={reason}>{reason}</li>
            ))}
          </ul>
        </div>
      ) : null}
      {slot.errorCode !== null ? (
        <p className={styles.errorCode}>ERROR / {slot.errorCode}</p>
      ) : null}
    </article>
  );
}

function StoryCard({
  selection,
}: Readonly<{ selection: ContentEditionSelectionViewModel }>) {
  return (
    <div className={styles.story} aria-labelledby={`story-${selection.id}`}>
      <div className={styles.storyTopline}>
        <span>STORY {selection.ordinal.toString().padStart(2, "0")}</span>
        <span data-state={selection.state}>{selection.stateLabel}</span>
      </div>
      <h4 id={`story-${selection.id}`}>{selection.title}</h4>
      <p className={styles.eventTime}>{selection.eventTimeLabel}</p>
      <dl className={styles.pipeline}>
        <div>
          <dt>文案</dt>
          <dd>{selection.copyStatus ?? "等待"}</dd>
        </div>
        <div>
          <dt>素材</dt>
          <dd>{selection.packageStatus ?? "等待"}</dd>
        </div>
        <div>
          <dt>投递</dt>
          <dd>{selection.deliveryStatus ?? "等待"}</dd>
        </div>
      </dl>
      <div className={styles.storyLinks}>
        {selection.packageUrl !== null ? (
          <a href={selection.packageUrl}>查看独立素材包</a>
        ) : (
          <span>素材包尚未就绪</span>
        )}
        {selection.sources.map((source) => (
          <a
            key={source.url}
            href={source.url}
            target="_blank"
            rel="noreferrer"
          >
            {source.label}
          </a>
        ))}
      </div>
    </div>
  );
}
