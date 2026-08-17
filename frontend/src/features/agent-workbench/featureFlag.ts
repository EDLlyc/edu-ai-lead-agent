type AgentWorkbenchImportMetaEnv = ImportMetaEnv & {
  readonly DEV: boolean;
  readonly VITE_AGENT_WORKBENCH_ENABLED?: string;
};

export function isAgentWorkbenchEnabled(
  environment: AgentWorkbenchImportMetaEnv = import.meta.env,
): boolean {
  return environment.DEV && environment.VITE_AGENT_WORKBENCH_ENABLED === "true";
}
