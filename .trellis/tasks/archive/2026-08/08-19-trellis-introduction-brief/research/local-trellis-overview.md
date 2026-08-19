# Local Trellis overview for the introduction brief

## Authoritative local sources

- `.agents/skills/trellis-meta/references/local-architecture/overview.md`
- `.trellis/workflow.md`
- `.trellis/config.yaml`
- `.trellis/spec/guides/index.md`

The report should rely on these project-local sources rather than marketing copy or memory.

## Verified definition

Trellis is a project-local workflow and persistence framework for AI-assisted software development. It puts development phases, task artifacts, project-specific specifications, and session knowledge inside the repository so AI tools can work with durable context instead of isolated prompts.

It is not:

- a large language model;
- a replacement for Git;
- a guarantee that generated code is correct;
- a hosted project-management service.

## Verified local model

The local architecture has three layers:

1. **Workflow layer** — `.trellis/workflow.md` defines phases, routing and next actions.
2. **Persistence layer** — `.trellis/tasks/`, `.trellis/spec/` and `.trellis/workspace/` hold task artifacts, project rules and session memory.
3. **Platform integration layer** — local skills, agents, hooks and commands connect the same workflow to AI development tools.

For a short introduction, present the user-facing concepts as four parts:

- Workflow: where the work is in its lifecycle;
- Tasks: what a specific piece of work is trying to achieve and what happened;
- Specs: how this project expects code and decisions to be made;
- Workspace / Memory: what carries progress and lessons across sessions.

## Verified task lifecycle

The workflow is organized around planning, execution and finishing:

```text
request
  -> plan and write task artifacts
  -> load relevant specifications and research
  -> implement
  -> independently check quality and consistency
  -> commit/archive and record session progress
  -> reuse the durable knowledge in later work
```

Planning is deliberately separated from implementation. A task may contain `prd.md`, `design.md`, `implement.md`, research notes and context manifests. The exact files depend on task complexity.

## Optional advanced capabilities

- Different implementation and checking roles can collaborate on complex work.
- Trellis Channel supports live multi-agent collaboration.
- `trellis mem` can retrieve prior local session history for cross-session continuity.

These are supporting capabilities, not the main definition of Trellis, and should receive no more than one short paragraph in the report.

## Presentation boundaries

- Keep the main report free of commands, internal state files and platform lists.
- Use a generic feature request as the example; do not expose this repository's business data or session logs.
- Explain that Git remains the version-control system and that tests/review remain necessary.
- Avoid numerical productivity claims and avoid saying Trellis automatically guarantees quality.
