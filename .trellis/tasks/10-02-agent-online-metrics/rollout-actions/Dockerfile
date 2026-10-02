# Watchdog + approved-actions overlay. Used only by the delivery-watchdog cron and edu-ai-ops-action.
FROM offline.local/edu-ai/edu-ai-lead-agent-backend@sha256:9c9d1c0117d2de62f06bcaa13a94f6f232d5e950d1b134b199e5c4a1a4ae6e9d
COPY app/application/services/agent_tracing.py /app/app/application/services/agent_tracing.py
COPY app/application/services/ops_diagnosis.py /app/app/application/services/ops_diagnosis.py
COPY app/delivery_watchdog_main.py /app/app/delivery_watchdog_main.py
COPY app/application/services/ops_actions.py /app/app/application/services/ops_actions.py
COPY app/infrastructure/db/ops_actions.py /app/app/infrastructure/db/ops_actions.py
COPY app/ops_actions_main.py /app/app/ops_actions_main.py
COPY app/application/services/ops_tools.py /app/app/application/services/ops_tools.py
COPY app/infrastructure/db/ops_reader.py /app/app/infrastructure/db/ops_reader.py
COPY files.txt /app/release-944f37a-actions-files.txt
