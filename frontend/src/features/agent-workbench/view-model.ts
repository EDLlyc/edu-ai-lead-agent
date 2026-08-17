export type AgentWorkbenchCitationViewModel = Readonly<{
  id: string;
  kind: string;
  kindLabel: string;
  sourceName: string;
  title: string;
  url: string | null;
  evidenceEligible: boolean;
}>;

export type AgentWorkbenchClaimViewModel = Readonly<{
  id: string;
  text: string;
  kind: string;
  kindLabel: string;
  citationIds: readonly string[];
}>;

export type AgentWorkbenchTraceDetailViewModel = Readonly<{
  label: string;
  value: string;
}>;

export type AgentWorkbenchTraceStepViewModel = Readonly<{
  id: string;
  ordinal: number;
  kind: string;
  kindLabel: string;
  status: string;
  statusLabel: string;
  code: string | null;
  toolName: string | null;
  toolLabel: string | null;
  displayLabel: string;
  durationMs: number | null;
  details: readonly AgentWorkbenchTraceDetailViewModel[];
  citationIds: readonly string[];
}>;

export type AgentWorkbenchMetricsViewModel = Readonly<{
  modelSteps: number;
  toolCalls: number;
  successfulToolCalls: number;
  durationMs: number;
  modelLatencyMs: number;
  toolLatencyMs: number;
  inputTokens: number | null;
  outputTokens: number | null;
  reasoningTokens: number | null;
}>;

export type AgentWorkbenchRunViewModel = Readonly<{
  runId: string;
  status: "completed" | "refused" | "budget-exhausted" | "failed" | "cancelled";
  statusLabel: string;
  summary: string;
  claims: readonly AgentWorkbenchClaimViewModel[];
  citations: readonly AgentWorkbenchCitationViewModel[];
  steps: readonly AgentWorkbenchTraceStepViewModel[];
  metrics: AgentWorkbenchMetricsViewModel;
  errorCode: string | null;
}>;

export type AgentWorkbenchScreenState =
  | Readonly<{ kind: "idle" }>
  | Readonly<{ kind: "running"; query: string }>
  | Readonly<{
      kind: "completed" | "refused" | "budget-exhausted";
      query: string;
      run: AgentWorkbenchRunViewModel;
    }>
  | Readonly<{ kind: "cancelled" }>
  | Readonly<{
      kind: "failed";
      code: string;
      message: string;
      requestId: string | null;
    }>;
