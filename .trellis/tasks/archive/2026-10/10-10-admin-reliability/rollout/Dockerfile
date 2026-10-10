# Offline overlay; build only after base manifest verification.
ARG BASE_IMAGE=offline.local/edu-ai/edu-ai-lead-agent-backend:admin-reliability-base-24e96708
FROM ${BASE_IMAGE}
COPY alembic/versions/20261010_0060_wechat_publish_occupancy.py /app/alembic/versions/20261010_0060_wechat_publish_occupancy.py
COPY alembic/versions/20261010_0061_model_key_load_errors.py /app/alembic/versions/20261010_0061_model_key_load_errors.py
COPY app/api/v1/routes/admin_models.py /app/app/api/v1/routes/admin_models.py
COPY app/api/v1/routes/admin_wechat.py /app/app/api/v1/routes/admin_wechat.py
COPY app/api_main.py /app/app/api_main.py
COPY app/application/services/wechat_admin.py /app/app/application/services/wechat_admin.py
COPY app/application/services/wechat_stats.py /app/app/application/services/wechat_stats.py
COPY app/infrastructure/db/models.py /app/app/infrastructure/db/models.py
COPY app/infrastructure/model_api_keys_overlay.py /app/app/infrastructure/model_api_keys_overlay.py
COPY app/infrastructure/wechat_official_account/admin_client.py /app/app/infrastructure/wechat_official_account/admin_client.py
COPY app/schemas/admin_models.py /app/app/schemas/admin_models.py
COPY app/schemas/admin_wechat.py /app/app/schemas/admin_wechat.py
COPY files.txt /app/release-admin-reliability-files.txt
