import { useMutation } from "@tanstack/react-query";
import { useEffect, useRef, useState } from "react";

import {
  AgentWorkbenchClientError,
  runAgentWorkbench,
  type AgentWorkbenchExecutor,
} from "./api";
import type {
  AgentWorkbenchRunViewModel,
  AgentWorkbenchScreenState,
} from "./view-model";

type PendingRun = Readonly<{
  sequence: number;
  controller: AbortController;
}>;

export function useAgentWorkbenchRun(
  executeRun: AgentWorkbenchExecutor = runAgentWorkbench,
) {
  const [state, setState] = useState<AgentWorkbenchScreenState>({
    kind: "idle",
  });
  const sequenceRef = useRef(0);
  const pendingRef = useRef<PendingRun | null>(null);
  const mutation = useMutation({
    mutationFn: ({
      query,
      signal,
    }: Readonly<{ query: string; signal: AbortSignal }>) =>
      executeRun(query, signal),
  });

  useEffect(
    () => () => {
      sequenceRef.current += 1;
      pendingRef.current?.controller.abort();
      pendingRef.current = null;
    },
    [],
  );

  async function run(query: string): Promise<void> {
    const normalizedQuery = query.trim();
    if (normalizedQuery.length === 0) {
      setState({
        kind: "failed",
        code: "agent_workbench_invalid_query",
        message: "请输入一个不为空的问题后再运行。",
        requestId: null,
      });
      return;
    }

    pendingRef.current?.controller.abort();
    const sequence = sequenceRef.current + 1;
    sequenceRef.current = sequence;
    const controller = new AbortController();
    pendingRef.current = { sequence, controller };
    setState({ kind: "running", query: normalizedQuery });

    try {
      const result = await mutation.mutateAsync({
        query: normalizedQuery,
        signal: controller.signal,
      });
      if (sequenceRef.current !== sequence) return;
      pendingRef.current = null;
      setState(projectResultState(normalizedQuery, result));
    } catch (error) {
      if (sequenceRef.current !== sequence) return;
      pendingRef.current = null;
      if (isAbortError(error)) {
        setState({ kind: "cancelled" });
        return;
      }
      const failure = projectFailure(error);
      setState({ kind: "failed", ...failure });
    }
  }

  function cancel(): void {
    if (pendingRef.current === null) return;
    sequenceRef.current += 1;
    pendingRef.current.controller.abort();
    pendingRef.current = null;
    mutation.reset();
    setState({ kind: "cancelled" });
  }

  function reset(): void {
    sequenceRef.current += 1;
    pendingRef.current?.controller.abort();
    pendingRef.current = null;
    mutation.reset();
    setState({ kind: "idle" });
  }

  return { state, run, cancel, reset } as const;
}

function projectResultState(
  query: string,
  result: AgentWorkbenchRunViewModel,
): AgentWorkbenchScreenState {
  switch (result.status) {
    case "completed":
      return { kind: "completed", query, run: result };
    case "refused":
      return { kind: "refused", query, run: result };
    case "budget-exhausted":
      return { kind: "budget-exhausted", query, run: result };
    case "cancelled":
      return { kind: "cancelled" };
    case "failed":
      return {
        kind: "failed",
        code: result.errorCode ?? "agent_workbench_run_failed",
        message:
          result.summary.length > 0
            ? result.summary
            : "工作台安全停止，未返回可展示的结果。",
        requestId: result.runId,
      };
  }
}

function projectFailure(error: unknown): Readonly<{
  code: string;
  message: string;
  requestId: string | null;
}> {
  if (error instanceof AgentWorkbenchClientError) {
    return {
      code: error.code,
      message: clientErrorMessage(error.code),
      requestId: error.requestId,
    };
  }
  return {
    code: "agent_workbench_request_failed",
    message: "无法连接本地工作台，请确认本地服务与显式开关均已启用。",
    requestId: null,
  };
}

function clientErrorMessage(code: string): string {
  const messages: Readonly<Record<string, string>> = {
    agent_workbench_disabled: "本地工作台尚未启用。",
    agent_workbench_loopback_required:
      "工作台只接受 127.0.0.1 或 ::1 的本地请求。",
    agent_workbench_invalid_request: "问题未通过工作台的长度或格式校验。",
    agent_model_unavailable: "本地模型适配器暂时不可用。",
    agent_model_invalid_output: "模型输出未通过工作台的结构校验。",
    agent_workbench_unavailable: "本地工作台暂时不可用。",
    agent_workbench_network_error: "无法连接 127.0.0.1:8010 的本地工作台。",
    agent_workbench_invalid_base_url: "工作台地址不是固定的本地回环地址。",
  };
  return messages[code] ?? "工作台安全停止，请根据错误码检查本地配置。";
}

function isAbortError(error: unknown): boolean {
  return (
    (error instanceof Error || error instanceof DOMException) &&
    error.name === "AbortError"
  );
}
