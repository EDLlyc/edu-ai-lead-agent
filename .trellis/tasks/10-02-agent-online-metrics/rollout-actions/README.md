# Rollout: approved actions, propose-only (release 944f37a)

Image `sha256:8f14b771fe2eab9e170d936e3092c6afbd684ca335f11e9216624983695cf640`
(tag `actions-944f37a`) = report image 9c9d1c01 + the 8 files in `files.txt`; bases 8/8 matched
the running app image; `smoke.py` passed offline (propose-only). Gate `predeploy gate PASS @ 944f37a`.

Deploy (owner confirmation required):
1. Back up `/usr/local/sbin/edu-ai-delivery-watchdog` as `*.before-944f37a-<ts>`, set its
   `IMAGE=` to the digest above (diagnosis v2 + proposals).
2. Install `scripts/ops/server/edu-ai-ops-action` as `/usr/local/sbin/edu-ai-ops-action`
   (root, 0755) with `IMAGE=` the same digest.
3. Do NOT create `scripts/ops-actions.env`: propose-only for the first week.

Enabling execution later: `echo OPS_ACTIONS_ENABLED=true > /opt/edu-ai-lead-agent/scripts/ops-actions.env`
(root, 0600). Rollback: restore the watchdog wrapper backup; remove `edu-ai-ops-action`.
