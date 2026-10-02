# Quality-report-only overlay: adds the 修复 Agent section. The six app services keep 32c89fe6.
FROM offline.local/edu-ai/edu-ai-lead-agent-backend@sha256:32c89fe63a7f3d4ca47e2e08a4db269e861606df9f36dd788f059b2fa5e1a060
COPY app/domain/repair_metrics.py /app/app/domain/repair_metrics.py
COPY app/infrastructure/db/repair_metrics.py /app/app/infrastructure/db/repair_metrics.py
COPY app/domain/quality_report.py /app/app/domain/quality_report.py
COPY app/infrastructure/db/quality_report.py /app/app/infrastructure/db/quality_report.py
COPY app/application/services/quality_report.py /app/app/application/services/quality_report.py
COPY files.txt /app/release-e8805a4-report-files.txt
