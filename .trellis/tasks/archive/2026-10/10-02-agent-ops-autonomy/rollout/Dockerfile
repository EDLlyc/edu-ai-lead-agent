# Watchdog-only overlay: the six app services keep 32c89fe6; only the delivery-watchdog cron uses this.
# Release 92c80df: a read-only diagnosis agent explains each delivery alert.
FROM offline.local/edu-ai/edu-ai-lead-agent-backend@sha256:32c89fe63a7f3d4ca47e2e08a4db269e861606df9f36dd788f059b2fa5e1a060
COPY app/application/services/agent_tracing.py /app/app/application/services/agent_tracing.py
COPY app/application/services/ops_diagnosis.py /app/app/application/services/ops_diagnosis.py
COPY app/delivery_watchdog_main.py /app/app/delivery_watchdog_main.py
COPY files.txt /app/release-92c80df-watchdog-files.txt
