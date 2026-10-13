FROM offline.local/edu-ai/edu-ai-lead-agent-backend@sha256:da05208214aa273084fd2bccb9ce86dbdc1c0ee2069a855706a5d058686e2df7
ARG FIX_COMMIT
LABEL org.opencontainers.image.revision=$FIX_COMMIT
LABEL org.opencontainers.image.base.name="offline.local/edu-ai/edu-ai-lead-agent-backend@sha256:da05208214aa273084fd2bccb9ce86dbdc1c0ee2069a855706a5d058686e2df7"
LABEL edu-ai.change="infographic-stage-unknown-log"
COPY --chown=0:0 app/application/services/wecom_news_infographic.py /app/app/application/services/wecom_news_infographic.py
