import { useState } from "react";

import { AgentWorkbenchView } from "./AgentWorkbenchView";
import { useAgentWorkbenchRun } from "./hooks";

export function AgentWorkbenchPanel() {
  const [query, setQuery] = useState("");
  const workbench = useAgentWorkbenchRun();

  return (
    <AgentWorkbenchView
      state={workbench.state}
      query={query}
      onQueryChange={setQuery}
      onRun={() => void workbench.run(query)}
      onCancel={workbench.cancel}
    />
  );
}
