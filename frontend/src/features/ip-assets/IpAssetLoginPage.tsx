import { useEffect, useRef, useState, type FormEvent } from "react";

import { grantIpAssetDemoAccess } from "./demoAccess";

import styles from "./IpAssetLoginPage.module.css";

type IpAssetLoginPageProps = {
  readonly onAuthenticated: (returnTarget: string) => void;
  readonly returnTarget: string;
};

type LoginStatus = "idle" | "invalid" | "submitting" | "storage-error";

const submitDelayMs = 280;

export function IpAssetLoginPage({
  onAuthenticated,
  returnTarget,
}: IpAssetLoginPageProps) {
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [status, setStatus] = useState<LoginStatus>("idle");
  const usernameRef = useRef<HTMLInputElement>(null);
  const passwordRef = useRef<HTMLInputElement>(null);
  const timerRef = useRef<number | null>(null);

  useEffect(
    () => () => {
      if (timerRef.current !== null) window.clearTimeout(timerRef.current);
    },
    [],
  );

  const handleSubmit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (status === "submitting") return;

    if (username.trim() === "") {
      setStatus("invalid");
      usernameRef.current?.focus();
      return;
    }
    if (password.trim() === "") {
      setStatus("invalid");
      passwordRef.current?.focus();
      return;
    }

    setStatus("submitting");
    timerRef.current = window.setTimeout(() => {
      timerRef.current = null;
      if (!grantIpAssetDemoAccess()) {
        setStatus("storage-error");
        return;
      }
      onAuthenticated(returnTarget);
    }, submitDelayMs);
  };

  const resetFeedback = () => {
    if (status === "invalid" || status === "storage-error") setStatus("idle");
  };

  const submitting = status === "submitting";

  return (
    <section className={styles.login} aria-labelledby="ip-login-title">
      <div className={styles.ambientGrid} aria-hidden="true" />
      <div className={styles.brandPanel}>
        <div className={styles.brandMark} aria-hidden="true">
          <span />
          IP
        </div>
        <div className={styles.brandCopy}>
          <p className={styles.eyebrow}>SAI VISUAL LIBRARY · INTERNAL</p>
          <h1 id="ip-login-title">让每一张 IP 图片，都能被再次找到。</h1>
          <p>赛先生与小赛数字资产库，连接共享图库、个人收藏与 AI 视觉创作。</p>
        </div>
        <div className={styles.assetStrip} aria-hidden="true">
          <span className={styles.assetOne}>赛</span>
          <span className={styles.assetTwo}>小赛</span>
          <span className={styles.assetThree}>✦</span>
        </div>
        <p className={styles.edition}>LOCAL DEMO / 2026</p>
      </div>

      <div className={styles.formPanel}>
        <div className={styles.formShell}>
          <div className={styles.formHeading}>
            <span aria-hidden="true">01</span>
            <div>
              <p>本地演示入口</p>
              <h2>欢迎回来</h2>
            </div>
          </div>

          <p className={styles.formIntro}>
            填写任意用户名和密码即可进入。输入内容不会发送，也不会保存在浏览器中。
          </p>

          <form
            className={styles.form}
            aria-busy={submitting}
            noValidate
            onSubmit={handleSubmit}
          >
            <label>
              <span>用户名</span>
              <input
                ref={usernameRef}
                type="text"
                name="username"
                autoComplete="username"
                autoFocus
                disabled={submitting}
                value={username}
                aria-invalid={status === "invalid" && username.trim() === ""}
                aria-describedby="ip-login-help ip-login-feedback"
                placeholder="例如：品牌内容组"
                onChange={(event) => {
                  setUsername(event.target.value);
                  resetFeedback();
                }}
              />
            </label>

            <label>
              <span>密码</span>
              <input
                ref={passwordRef}
                type="password"
                name="password"
                autoComplete="current-password"
                disabled={submitting}
                value={password}
                aria-invalid={status === "invalid" && password.trim() === ""}
                aria-describedby="ip-login-help ip-login-feedback"
                placeholder="任意填写"
                onChange={(event) => {
                  setPassword(event.target.value);
                  resetFeedback();
                }}
              />
            </label>

            <p className={styles.help} id="ip-login-help">
              登录只在当前浏览器标签页有效，关闭后需要重新进入。
            </p>

            <button type="submit" disabled={submitting}>
              <span>{submitting ? "正在进入资产中心…" : "进入资产中心"}</span>
              <span aria-hidden="true">→</span>
            </button>

            <div
              className={styles.feedback}
              id="ip-login-feedback"
              aria-live="polite"
              aria-atomic="true"
            >
              {status === "invalid" ? (
                <p role="alert">请填写用户名和密码后再进入。</p>
              ) : null}
              {status === "submitting" ? (
                <p>信息完整，正在打开工作台。</p>
              ) : null}
              {status === "storage-error" ? (
                <p role="alert">
                  当前浏览器无法保存本地会话，请允许会话存储后重试。
                </p>
              ) : null}
            </div>
          </form>

          <p className={styles.boundaryNote} role="note">
            此页面仅作为 MVP
            演示入口，不验证真实员工身份，也不限制直接访问后端接口。
          </p>
        </div>
      </div>
    </section>
  );
}
