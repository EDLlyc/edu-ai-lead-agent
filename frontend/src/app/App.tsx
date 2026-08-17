import { lazy, Suspense } from "react";

import { BrandKnowledgePanel } from "@/features/brand/BrandKnowledgePanel";
import { ContentEditionBoard } from "@/features/content-edition/ContentEditionBoard";
import { isAgentWorkbenchEnabled } from "@/features/agent-workbench/featureFlag";
import { MaterialPackagePanel } from "@/features/material/MaterialPackagePanel";
import { PreviewPanel } from "@/features/preview/PreviewPanel";

import styles from "./App.module.css";

const LocalAgentWorkbenchPanel = import.meta.env.DEV
  ? lazy(async () => {
      const module =
        await import("@/features/agent-workbench/AgentWorkbenchPanel");
      return { default: module.AgentWorkbenchPanel };
    })
  : null;

export function App() {
  const showAgentWorkbench =
    LocalAgentWorkbenchPanel !== null && isAgentWorkbenchEnabled();

  return (
    <>
      <a className={styles.skipLink} href="#main-content">
        跳到主要内容
      </a>
      <div className={styles.grain} aria-hidden="true" />
      <header className={styles.header}>
        <a
          className={styles.wordmark}
          href="/"
          aria-label="Edu AI 内部控制台首页"
        >
          <span aria-hidden="true">EAL</span>
          <span>Brand Knowledge System</span>
        </a>
        <div className={styles.headerMeta} aria-label="品牌知识库元数据">
          <span>BRAND / 赛先生</span>
          <span>TARGET / 家长</span>
          <span className={styles.headerSignal}>PRIVATE</span>
        </div>
      </header>

      <main id="main-content">
        <section className={styles.hero} aria-labelledby="page-title">
          <div className={styles.heroIndex} aria-hidden="true">
            RAG—02
          </div>
          <div className={styles.heroCopy}>
            <p className={styles.eyebrow}>CONTENT MVP / BRAND MEMORY</p>
            <h1 id="page-title">
              品牌知识
              <span>文案生成上下文</span>
            </h1>
            <p className={styles.lede}>
              上传赛先生品牌资料，异步完成解析、切块和向量化；激活后的规则会注入朋友圈文案生成流程，帮助统一品牌表达与风险边界。
            </p>
          </div>
          <div
            className={styles.boundaryNote}
            role="note"
            aria-label="当前系统边界"
          >
            <span>BOUNDARY / BRAND ≠ EVIDENCE</span>
            <strong>品牌资料不能证明外部事实</strong>
            <p>
              事实仍须绑定已采集的权威原文；品牌知识只为内部生成节点提供表达、语气、安全和视觉规则。
            </p>
          </div>
        </section>

        {showAgentWorkbench && LocalAgentWorkbenchPanel !== null ? (
          <Suspense
            fallback={
              <section
                className={styles.statusSection}
                aria-label="本地 Agent 研究工作台"
              >
                <p role="status">正在载入本地 Agent 工作台…</p>
              </section>
            }
          >
            <LocalAgentWorkbenchPanel />
          </Suspense>
        ) : null}

        <BrandKnowledgePanel />
        <PreviewPanel />
        <ContentEditionBoard />
        <MaterialPackagePanel />

        <section className={styles.safetyRail} aria-labelledby="safety-title">
          <div>
            <p>SECURITY INTERLOCK</p>
            <h2 id="safety-title">私有原件，人工审核边界</h2>
          </div>
          <ul>
            <li>
              <span>01</span> 原件只进入私有 MinIO 桶
            </li>
            <li>
              <span>02</span> 列表不返回完整文档正文
            </li>
            <li>
              <span>03</span> 不提供自动发布操作
            </li>
          </ul>
        </section>
      </main>

      <footer className={styles.footer}>
        <span>EDU AI LEAD AGENT</span>
        <span>COPY GENERATION CONTEXT / 2026</span>
      </footer>
    </>
  );
}
