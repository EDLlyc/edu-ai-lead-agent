import { CommandCard } from "./CommandCard";
import styles from "./App.module.css";

const environmentUnits = [
  {
    code: "PY-311",
    name: "Conda / Python",
    detail: "edu-ai · Python 3.11",
  },
  {
    code: "API-001",
    name: "FastAPI Shell",
    detail: "Health contract ready",
  },
  {
    code: "DB-016",
    name: "PostgreSQL",
    detail: "Postgres 16 · pgvector 0.8.1",
  },
  {
    code: "OBJ-01",
    name: "Object Storage",
    detail: "MinIO · local bucket",
  },
  {
    code: "WEB-020",
    name: "React Toolchain",
    detail: "Node 20 · Vite · strict TS",
  },
] as const;

const commands = [
  {
    index: "01",
    title: "Install toolchains",
    description: "安装后端可编辑包与锁定的 npm 依赖。",
    command: "make setup",
  },
  {
    index: "02",
    title: "Start infrastructure",
    description: "启动仅绑定本机端口的 pgvector 与 MinIO。",
    command: "make infra-up",
  },
  {
    index: "03",
    title: "Verify the system",
    description: "检查解释器、依赖、容器健康与本地存储。",
    command: "make doctor",
  },
] as const;

export function App() {
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
          aria-label="Edu AI 开发控制台首页"
        >
          <span aria-hidden="true">EAL</span>
          <span>Development System</span>
        </a>
        <div className={styles.headerMeta} aria-label="项目环境元数据">
          <span>ENV / LOCAL</span>
          <span>UTC+08:00</span>
          <span className={styles.headerSignal}>CONFIGURED</span>
        </div>
      </header>

      <main id="main-content">
        <section className={styles.hero} aria-labelledby="page-title">
          <div className={styles.heroIndex} aria-hidden="true">
            ENV—00
          </div>
          <div className={styles.heroCopy}>
            <p className={styles.eyebrow}>FIRST SLICE / PRE-FLIGHT</p>
            <h1 id="page-title">
              开发环境
              <span>已完成配置</span>
            </h1>
            <p className={styles.lede}>
              本页面验证 React 构建链已经接通。实际服务健康状态以终端中的
              <code>make doctor</code> 为准。
            </p>
          </div>
          <div
            className={styles.boundaryNote}
            role="note"
            aria-label="当前系统边界"
          >
            <span>BOUNDARY / 01</span>
            <strong>环境壳，不是业务流水线</strong>
            <p>尚未启用采集、模型调用、素材生成或自动发布。</p>
          </div>
        </section>

        <section
          className={styles.statusSection}
          aria-labelledby="status-title"
        >
          <div className={styles.sectionHeading}>
            <div>
              <p>CONFIGURATION MATRIX</p>
              <h2 id="status-title">开发单元</h2>
            </div>
            <p className={styles.sectionCode}>05 UNITS / LOCALHOST ONLY</p>
          </div>

          <div className={styles.statusGrid}>
            {environmentUnits.map((unit) => (
              <article className={styles.statusCard} key={unit.code}>
                <div className={styles.cardTopline}>
                  <span>{unit.code}</span>
                  <span className={styles.configuredBadge}>
                    <span aria-hidden="true" /> CONFIGURED
                  </span>
                </div>
                <h3>{unit.name}</h3>
                <p>{unit.detail}</p>
              </article>
            ))}
          </div>
        </section>

        <section
          className={styles.commandSection}
          aria-labelledby="command-title"
        >
          <div className={styles.sectionHeading}>
            <div>
              <p>COMMAND SEQUENCE</p>
              <h2 id="command-title">启动顺序</h2>
            </div>
            <p className={styles.sectionCode}>NON-DESTRUCTIVE DEFAULTS</p>
          </div>
          <div className={styles.commandGrid}>
            {commands.map((command) => (
              <CommandCard key={command.index} {...command} />
            ))}
          </div>
        </section>

        <section className={styles.safetyRail} aria-labelledby="safety-title">
          <div>
            <p>SECURITY INTERLOCK</p>
            <h2 id="safety-title">私有仓库也不存放真实密钥</h2>
          </div>
          <ul>
            <li>
              <span>01</span> `.env` 保持未跟踪
            </li>
            <li>
              <span>02</span> AI 平台凭据默认留空
            </li>
            <li>
              <span>03</span> 停止容器不会删除数据卷
            </li>
          </ul>
        </section>
      </main>

      <footer className={styles.footer}>
        <span>EDU AI LEAD AGENT</span>
        <span>DEVELOPMENT ENVIRONMENT / 2026</span>
      </footer>
    </>
  );
}
