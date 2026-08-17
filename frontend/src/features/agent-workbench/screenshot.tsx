import { StrictMode } from "react";
import { createRoot } from "react-dom/client";

import "@/styles/tokens.css";
import "@/styles/globals.css";

import { AgentWorkbenchView } from "./AgentWorkbenchView";
import {
  agentWorkbenchFixtureQuery,
  agentWorkbenchFixtureRun,
} from "./fixture";

const root = document.getElementById("agent-workbench-screenshot");

if (root === null) {
  throw new Error("agent workbench screenshot root is missing");
}

createRoot(root).render(
  <StrictMode>
    <AgentWorkbenchView
      state={{
        kind: "completed",
        query: agentWorkbenchFixtureQuery,
        run: agentWorkbenchFixtureRun,
      }}
      query={agentWorkbenchFixtureQuery}
      onQueryChange={() => undefined}
      onRun={() => undefined}
      onCancel={() => undefined}
    />
  </StrictMode>,
);
