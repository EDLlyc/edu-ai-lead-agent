import { describe, expect, it } from "vitest";

import {
  DEFAULT_AGENT_WORKBENCH_API_BASE_URL,
  getAgentWorkbenchApiBaseUrl,
} from "./config";
import { isAgentWorkbenchEnabled } from "./featureFlag";

function environment(
  values: Readonly<{
    DEV?: boolean;
    VITE_AGENT_WORKBENCH_ENABLED?: string;
    VITE_AGENT_WORKBENCH_API_BASE_URL?: string;
  }> = {},
): ImportMetaEnv & {
  readonly DEV: boolean;
  readonly VITE_AGENT_WORKBENCH_ENABLED?: string;
  readonly VITE_AGENT_WORKBENCH_API_BASE_URL?: string;
} {
  return {
    BASE_URL: "/",
    MODE: values.DEV === false ? "production" : "development",
    PROD: values.DEV === false,
    SSR: false,
    DEV: values.DEV ?? true,
    ...(values.VITE_AGENT_WORKBENCH_ENABLED === undefined
      ? {}
      : {
          VITE_AGENT_WORKBENCH_ENABLED: values.VITE_AGENT_WORKBENCH_ENABLED,
        }),
    ...(values.VITE_AGENT_WORKBENCH_API_BASE_URL === undefined
      ? {}
      : {
          VITE_AGENT_WORKBENCH_API_BASE_URL:
            values.VITE_AGENT_WORKBENCH_API_BASE_URL,
        }),
  };
}

function withFixtureUserinfo(value: string): string {
  const url = new URL(value);
  url.username = "fixture-user";
  return url.href;
}

describe("agent workbench local configuration", () => {
  it("requires both Vite development mode and the exact opt-in value", () => {
    expect(
      isAgentWorkbenchEnabled(
        environment({ DEV: true, VITE_AGENT_WORKBENCH_ENABLED: "true" }),
      ),
    ).toBe(true);
    expect(
      isAgentWorkbenchEnabled(
        environment({ DEV: false, VITE_AGENT_WORKBENCH_ENABLED: "true" }),
      ),
    ).toBe(false);
    expect(
      isAgentWorkbenchEnabled(
        environment({ DEV: true, VITE_AGENT_WORKBENCH_ENABLED: "TRUE" }),
      ),
    ).toBe(false);
    expect(isAgentWorkbenchEnabled(environment({ DEV: true }))).toBe(false);
  });

  it("uses the fixed loopback launcher origin by default", () => {
    expect(getAgentWorkbenchApiBaseUrl(environment())).toBe(
      DEFAULT_AGENT_WORKBENCH_API_BASE_URL,
    );
    expect(
      getAgentWorkbenchApiBaseUrl(
        environment({
          VITE_AGENT_WORKBENCH_API_BASE_URL: "http://[::1]:8010",
        }),
      ),
    ).toBe("http://[::1]:8010");
  });

  it.each([
    "http://localhost:8010",
    "http://0.0.0.0:8010",
    "http://127.0.0.1:8000",
    "https://127.0.0.1:8010",
    withFixtureUserinfo("http://127.0.0.1:8010"),
    "http://127.0.0.1:8010/api",
    "http://127.0.0.1:8010?mode=live",
    "not-a-url",
  ])("rejects non-canonical local origin %s", (baseUrl) => {
    expect(() =>
      getAgentWorkbenchApiBaseUrl(
        environment({ VITE_AGENT_WORKBENCH_API_BASE_URL: baseUrl }),
      ),
    ).toThrow("agent_workbench_invalid_base_url");
  });
});
