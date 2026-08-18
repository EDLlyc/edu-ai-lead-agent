# GitHub repository page publication result

## Outcome

- Repository: `https://github.com/EDLlyc/edu-ai-lead-agent`
- Default branch: `main`
- Previous GitHub head: `4148acb581434c07ae1c08398c94e879acf00ef9`
- Published GitHub head: `a876c5c9a369266eb027f2f983b75497c6726417`
- Push mode: fast-forward only; no force push, merge, rebase, or history rewrite.
- The published history contains the verified Agent Workbench portfolio commit `b1d9fd0`.

## Remote verification

- GitHub API returned the exact published `main` SHA.
- Remote README contains:
  - `docs/portfolio/assets/agent-workbench-real-runs-overview.png`
  - `docs/portfolio/runs/agent-workbench/f5cd8de936a5-20260818T063838Z/manifest.json`
- Both referenced assets exist through the GitHub Contents API:
  - overview PNG: 392,815 bytes
  - evidence manifest: 7,878 bytes
- Repository visibility remains `PRIVATE`.
- GitHub Pages API still returns not found; Pages was not enabled.

## Safety and scope evidence

- Before the push, `release_tool.py scan-committed-secrets` passed for all 1,068 files in the target commit.
- GitHub `main` was proven to be an ancestor of local `main` immediately before publication.
- Codeup `origin`, production services, providers, WeCom, repository visibility, and GitHub Pages were untouched.
- The user-owned uncommitted report files remain local dirty changes and were not staged, committed, or pushed:
  - `reports/wechat-digital-employee-briefing-2026-08-18.pdf`
  - `reports/wechat-digital-employee-briefing-2026-08-18.tex`
