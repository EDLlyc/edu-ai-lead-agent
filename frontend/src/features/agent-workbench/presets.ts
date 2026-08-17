export const AGENT_WORKBENCH_QUERY_LIMIT = 500;

export const agentWorkbenchPresets = [
  {
    id: "evidence",
    label: "证据核验",
    query: "这条 AI 教育事件有哪些可靠证据，适合怎样向家长解释？",
  },
  {
    id: "brand-boundary",
    label: "品牌边界",
    query:
      "综合核验 AI 教育事件的外部事实与赛先生品牌语气；事实证据与品牌上下文必须分开。",
  },
  {
    id: "validation",
    label: "文案校验",
    query:
      "对示例家长沟通文案进行文案检查，只报告确定性问题与引用边界，不执行任何修复。",
  },
] as const;
