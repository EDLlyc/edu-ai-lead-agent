import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, renderHook, waitFor } from "@testing-library/react";
import type { PropsWithChildren } from "react";
import { describe, expect, it, vi } from "vitest";

import { AgentWorkbenchClientError, type AgentWorkbenchExecutor } from "./api";
import { agentWorkbenchFixtureRun } from "./fixture";
import { useAgentWorkbenchRun } from "./hooks";
import type { AgentWorkbenchRunViewModel } from "./view-model";

function createWrapper() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return function TestProviders({ children }: PropsWithChildren) {
    return (
      <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
    );
  };
}

function deferred<T>() {
  let resolvePromise: (value: T) => void = () => {
    throw new Error("deferred promise was not initialized");
  };
  const promise = new Promise<T>((resolve) => {
    resolvePromise = resolve;
  });
  return { promise, resolve: resolvePromise } as const;
}

describe("useAgentWorkbenchRun", () => {
  it("projects a successful run into an explicit terminal screen state", async () => {
    const executeRun = vi.fn<AgentWorkbenchExecutor>(() =>
      Promise.resolve(agentWorkbenchFixtureRun),
    );
    const { result } = renderHook(() => useAgentWorkbenchRun(executeRun), {
      wrapper: createWrapper(),
    });

    await act(() => result.current.run("  核验本地证据  "));

    expect(executeRun).toHaveBeenCalledOnce();
    expect(executeRun.mock.calls[0]?.[0]).toBe("核验本地证据");
    expect(result.current.state).toMatchObject({
      kind: "completed",
      query: "核验本地证据",
      run: { runId: agentWorkbenchFixtureRun.runId },
    });
  });

  it("cancels the owned request without retrying it", async () => {
    const executeRun = vi.fn<AgentWorkbenchExecutor>(
      (_query, signal) =>
        new Promise((_resolve, reject) => {
          signal?.addEventListener(
            "abort",
            () => reject(new DOMException("cancelled", "AbortError")),
            { once: true },
          );
        }),
    );
    const { result } = renderHook(() => useAgentWorkbenchRun(executeRun), {
      wrapper: createWrapper(),
    });

    act(() => void result.current.run("核验后取消"));
    await waitFor(() => expect(result.current.state.kind).toBe("running"));
    act(() => result.current.cancel());

    expect(result.current.state).toEqual({ kind: "cancelled" });
    expect(executeRun).toHaveBeenCalledOnce();
  });

  it("ignores a stale response after a newer run completes", async () => {
    const first = deferred<AgentWorkbenchRunViewModel>();
    const second = deferred<AgentWorkbenchRunViewModel>();
    let callCount = 0;
    const executeRun = vi.fn<AgentWorkbenchExecutor>(() => {
      callCount += 1;
      return callCount === 1 ? first.promise : second.promise;
    });
    const { result } = renderHook(() => useAgentWorkbenchRun(executeRun), {
      wrapper: createWrapper(),
    });

    let firstRun: Promise<void> = Promise.resolve();
    let secondRun: Promise<void> = Promise.resolve();
    act(() => {
      firstRun = result.current.run("第一次问题");
    });
    act(() => {
      secondRun = result.current.run("第二次问题");
    });

    await act(async () => {
      second.resolve({
        ...agentWorkbenchFixtureRun,
        runId: "00000000-0000-4000-8000-000000000902",
        summary: "第二次结果",
      });
      await secondRun;
    });
    expect(result.current.state).toMatchObject({
      kind: "completed",
      query: "第二次问题",
      run: { summary: "第二次结果" },
    });

    await act(async () => {
      first.resolve({
        ...agentWorkbenchFixtureRun,
        runId: "00000000-0000-4000-8000-000000000903",
        summary: "过期结果",
      });
      await firstRun;
    });
    expect(result.current.state).toMatchObject({
      kind: "completed",
      query: "第二次问题",
      run: { summary: "第二次结果" },
    });
  });

  it("translates transport failure into bounded guidance", async () => {
    const executeRun = vi.fn<AgentWorkbenchExecutor>(() =>
      Promise.reject(
        new AgentWorkbenchClientError(
          "agent_workbench_loopback_required",
          403,
          "request-safe-1",
        ),
      ),
    );
    const { result } = renderHook(() => useAgentWorkbenchRun(executeRun), {
      wrapper: createWrapper(),
    });

    await act(() => result.current.run("非回环请求"));

    expect(result.current.state).toEqual({
      kind: "failed",
      code: "agent_workbench_loopback_required",
      message: "工作台只接受 127.0.0.1 或 ::1 的本地请求。",
      requestId: "request-safe-1",
    });
  });
});
