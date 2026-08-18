# Agent Workbench real loopback run evidence

- Capture ID: `f5cd8de936a5-20260818T063838Z`
- Source commit: `f5cd8de936a57dfd61c01101b7cb2a2412b2eb25`
- Captured at: `2026-08-18T06:38:38Z`
- Mode: `deterministic-fixture`

This deterministic fixture capture proves the reproducible execution chain and safety contract; it is not evidence of live-model intelligence.

| Case | Terminal | Tools | Citations | Steps | Model / tool calls | Expected |
| --- | --- | --- | ---: | ---: | ---: | --- |
| `multi-tool-research` | `completed` | search_evidence → get_event → retrieve_brand_context | 2 | 11 | 4 / 3 | yes |
| `copy-validation` | `completed` | validate_copy | 0 | 5 | 2 / 1 | yes |
| `safety-refusal` | `refused` | none | 0 | 2 | 1 / 0 | yes |

Generate a new evidence package with `make agent-portfolio-capture`. The command starts real Uvicorn and Vite services on exact loopback ports, uses Playwright without route interception, verifies API/UI semantics, strips PNG metadata, hashes artifacts, and cleans up child processes.
