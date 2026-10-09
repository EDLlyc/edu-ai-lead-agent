# Python-only overlay: 运营后台 accounts, own password, source articles, audit filters (no migration).
FROM offline.local/edu-ai/edu-ai-lead-agent-backend@sha256:5a5fb24ccaccf1894e3d857e583f412fb01526dd4bd5f71f83125bd2482f92b7
COPY app/api/v1/routes/admin.py /app/app/api/v1/routes/admin.py
COPY app/api/v1/routes/admin_accounts.py /app/app/api/v1/routes/admin_accounts.py
COPY app/api/v1/routes/admin_sources.py /app/app/api/v1/routes/admin_sources.py
COPY app/api_main.py /app/app/api_main.py
COPY app/application/services/admin_accounts.py /app/app/application/services/admin_accounts.py
COPY app/domain/admin_auth.py /app/app/domain/admin_auth.py
COPY app/infrastructure/db/admin_auth.py /app/app/infrastructure/db/admin_auth.py
COPY app/infrastructure/db/source_admin.py /app/app/infrastructure/db/source_admin.py
COPY app/schemas/admin.py /app/app/schemas/admin.py
COPY app/schemas/admin_sources.py /app/app/schemas/admin_sources.py
COPY files.txt /app/release-0854380-files.txt
