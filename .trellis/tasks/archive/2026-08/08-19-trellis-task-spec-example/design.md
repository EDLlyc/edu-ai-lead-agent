# Trellis 任务规范示例：设计说明

## 1. Deliverables

- 更新 `reports/trellis-introduction-brief-2026-08-19.tex`
- 更新 `reports/trellis-introduction-brief-2026-08-19.pdf`
- 新增 `.trellis/tasks/08-19-trellis-task-spec-example/research/real-task-structure.md`

## 2. Page 5 Replacement

删除现有“真实项目运行记录”页，并将原总结内容回到第 5 页。页面顶部新增“一个真实任务，怎样连接规则与结果”区块：

```text
Task（真实任务结构的简化示意）
  目标：做一份 5 分钟的 Trellis 简介
  记录：需求 / 设计 / 执行 / 结果
        ↓ 读取
Spec（项目规则）
  先确认范围、再修改；用项目已有规范约束做法
        ↓ 产出
Output（可复核交付）
  PDF + 编译检查 + 结果记录
```

这不是原始文件截图，也不是所有任务的硬性模板。标题下增加一句小注：任务会按复杂度保留必要工件，简单事项可以更轻。

## 3. Visual Design

- 移除 `graphicx` 包和全部图片引用。
- 三张卡片沿用 Navy / Purple / Teal 体系；每张卡片各 2--3 行短句。
- 连接箭头强调“任务读取规范，产生可检查结果”，但不暗示 Spec 会自动生成内容或替代质量判断。
- 原页“适合的工作 / 不该期待的事”双栏与总结卡保持不变，整体仍为 5 页。

## 4. Accuracy Boundaries

- Task 示例来源是该报告对应的真实任务结构，但正文不写任务目录、日期、用户名、Git 提交或会话详情。
- Spec 只概括本项目真实规则入口的职责；不虚构具体强制流程。
- Output 包含可编辑源、PDF、构建和检查记录，作为本次任务的真实结果；不扩大成所有 Trellis 项目的保证。
- Git、模型、测试和人工评审的边界沿用原报告。

## 5. Validation

- 确认 TeX 中没有 `graphicx`、`includegraphics`、`agent-workbench`、`deterministic`、`loopback` 或 portfolio 截图路径。
- 编译后确认 PDF 恢复 5 页，页面 5 三张卡片和原总结区块无重叠。
- 检查字体、文本提取、日志、敏感信息和 Git diff。
