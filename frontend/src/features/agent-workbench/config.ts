export const DEFAULT_AGENT_WORKBENCH_API_BASE_URL = "http://127.0.0.1:8010";

type AgentWorkbenchConfigEnv = ImportMetaEnv & {
  readonly VITE_AGENT_WORKBENCH_API_BASE_URL?: string;
};

export function getAgentWorkbenchApiBaseUrl(
  environment: AgentWorkbenchConfigEnv = import.meta.env,
): string {
  const configured = environment.VITE_AGENT_WORKBENCH_API_BASE_URL?.trim();
  const candidate =
    configured === undefined || configured.length === 0
      ? DEFAULT_AGENT_WORKBENCH_API_BASE_URL
      : configured;

  let url: URL;
  try {
    url = new URL(candidate);
  } catch {
    throw new Error("agent_workbench_invalid_base_url");
  }

  const isLoopback = url.hostname === "127.0.0.1" || url.hostname === "[::1]";
  if (
    url.protocol !== "http:" ||
    !isLoopback ||
    url.port !== "8010" ||
    url.username.length > 0 ||
    url.password.length > 0 ||
    url.pathname !== "/" ||
    url.search.length > 0 ||
    url.hash.length > 0
  ) {
    throw new Error("agent_workbench_invalid_base_url");
  }

  return url.origin;
}
