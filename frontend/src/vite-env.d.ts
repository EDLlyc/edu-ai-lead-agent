/// <reference types="vite/client" />

interface ImportMetaEnv {
  readonly VITE_API_BASE_URL?: string;
  readonly VITE_AGENT_WORKBENCH_API_BASE_URL?: string;
  readonly VITE_AGENT_WORKBENCH_ENABLED?: string;
  readonly VITE_OFFICIAL_ACCOUNT_LOCAL_ENABLED?: string;
  readonly VITE_IP_ASSET_HUB_ENABLED?: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}
