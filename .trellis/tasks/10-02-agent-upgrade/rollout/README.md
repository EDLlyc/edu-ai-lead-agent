# Rollout: agent-first copy repair (release de22d32)

LIVE 2026-10-02 19:30 (owner: "同意"); env backups `*.before-de22d32-20261002T193042`.

Image `sha256:32c89fe63a7f3d4ca47e2e08a4db269e861606df9f36dd788f059b2fa5e1a060` = b8fa7ada + 5 app
files (`files.txt`), built on the host as `edu-ai-lead-agent-backend:release-de22d32`; base hashes
5/5 matched the running container; `smoke.py` passed offline (`--network none`). Gate
`predeploy gate PASS @ de22d32`.

Compose and `.env` do not set `COPY_REPAIR_MODE`, so the code default `agent_first` applies.

Deploy (owner confirmation required; not during a slot, no copy job running):
back up `.env`/`.release.env` as `*.before-de22d32-<ts>`, set `APP_IMAGE` to the digest above,
recreate the six app services with `up -d --no-deps`.

Rollback: restore both env files and recreate the six services (or set `COPY_REPAIR_MODE=regenerate`
in `.env` and pass it through compose for the content worker).

Check after the first blocked draft: `copy_generation_attempts.safe_metadata->>'repair_method'`
(`agent` on an accepted draft 2) or a `workflow`/`failed` attempt with a `repair_agent_*` code.
