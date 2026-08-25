import { lazy, Suspense, useEffect, useState, type ReactNode } from "react";

import {
  currentIpAssetReturnTarget,
  hasIpAssetDemoAccess,
  replaceIpAssetLocation,
  safeIpAssetReturnTarget,
} from "@/features/ip-assets/demoAccess";
import { isIpAssetHubEnabled } from "@/features/ip-assets/featureFlag";
import { IpAssetLoginPage } from "@/features/ip-assets/IpAssetLoginPage";

import { App } from "./App";
import styles from "./Application.module.css";
import { resolveApplicationPath } from "./pathResolver";

const IpAssetPage = lazy(async () => {
  const module = await import("@/features/ip-assets/IpAssetPage");
  return { default: module.IpAssetPage };
});

const IpAssetCreationPage = lazy(async () => {
  const module = await import("@/features/ip-assets/IpAssetCreationPage");
  return { default: module.IpAssetCreationPage };
});

export function Application() {
  const location = useApplicationLocation();
  const route = resolveApplicationPath(location.pathname);

  if (route === "console") return <App />;
  if (
    route === "ip-assets" ||
    route === "ip-assets-create" ||
    route === "ip-assets-login"
  ) {
    if (!isIpAssetHubEnabled()) {
      return (
        <StandaloneDocument title="页面不可用">
          <UnavailableRoute
            description="此本地功能当前未启用。请确认环境配置后重新打开该地址。"
            label="LOCAL FEATURE DISABLED"
          />
        </StandaloneDocument>
      );
    }
    if (route === "ip-assets-login") {
      const returnTarget = safeIpAssetReturnTarget(
        new URLSearchParams(location.search).get("returnTo"),
      );
      return (
        <StandaloneDocument title="登录 · IP 数字资产中心">
          <IpAssetLoginPage
            returnTarget={returnTarget}
            onAuthenticated={replaceIpAssetLocation}
          />
        </StandaloneDocument>
      );
    }
    if (!hasIpAssetDemoAccess()) {
      return (
        <StandaloneDocument title="登录 · IP 数字资产中心">
          <IpAssetLoginPage
            returnTarget={currentIpAssetReturnTarget()}
            onAuthenticated={replaceIpAssetLocation}
          />
        </StandaloneDocument>
      );
    }
    const creation = route === "ip-assets-create";
    return (
      <StandaloneDocument
        title={creation ? "AI 视觉创作室" : "IP 数字资产中心"}
      >
        <Suspense fallback={<IpAssetPageLoading creation={creation} />}>
          {creation ? <IpAssetCreationPage /> : <IpAssetPage />}
        </Suspense>
      </StandaloneDocument>
    );
  }
  return (
    <StandaloneDocument title="页面未找到">
      <UnavailableRoute
        description="当前地址不存在，返回本地开发控制台后可以继续使用其他功能。"
        label="404 / NOT FOUND"
      />
    </StandaloneDocument>
  );
}

function readApplicationLocation() {
  return {
    pathname: window.location.pathname,
    search: window.location.search,
  };
}

function useApplicationLocation() {
  const [location, setLocation] = useState(readApplicationLocation);

  useEffect(() => {
    const handlePopState = () => setLocation(readApplicationLocation());
    window.addEventListener("popstate", handlePopState);
    return () => window.removeEventListener("popstate", handlePopState);
  }, []);

  return location;
}

function StandaloneDocument({
  children,
  title,
}: Readonly<{ children: ReactNode; title: string }>) {
  useEffect(() => {
    const previousTitle = document.title;
    document.title = title;
    return () => {
      document.title = previousTitle;
    };
  }, [title]);

  return (
    <div className={styles.standalonePage}>
      <a className={styles.skipLink} href="#standalone-main">
        跳到主要内容
      </a>
      <main className={styles.standaloneMain} id="standalone-main">
        {children}
      </main>
    </div>
  );
}

function IpAssetPageLoading({
  creation = false,
}: Readonly<{ creation?: boolean }>) {
  return (
    <section className={styles.routeState} aria-labelledby="loading-title">
      <div className={styles.routeStateCard}>
        <p className={styles.routeStateKicker}>SAI VISUAL LIBRARY</p>
        <h1 id="loading-title">
          {creation ? "正在载入 AI 视觉创作室" : "正在载入 IP 数字资产中心"}
        </h1>
        <p role="status">
          {creation
            ? "正在准备参考素材与个人素材架…"
            : "正在准备本地资产图库与检索工具…"}
        </p>
      </div>
    </section>
  );
}

function UnavailableRoute({
  description,
  label,
}: Readonly<{ description: string; label: string }>) {
  return (
    <section className={styles.routeState} aria-labelledby="route-state-title">
      <div className={styles.routeStateCard}>
        <p className={styles.routeStateKicker}>{label}</p>
        <h1 id="route-state-title">页面不可用</h1>
        <p>{description}</p>
        <a href="/">返回本地控制台</a>
      </div>
    </section>
  );
}
