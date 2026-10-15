FROM offline.local/edu-ai/edu-ai-lead-agent-backend@sha256:a3a3e7f766646415caf89688961e2289daa04fae5a8b0445ca1059f6da485a06
ARG FIX_COMMIT
ARG TREE_SHA256
LABEL org.opencontainers.image.revision=$FIX_COMMIT
LABEL edu-ai.change="visitor-display-adapter" edu-ai.tree.sha256=$TREE_SHA256
# Pinned release f06694a + reviewed visitor-display files from a commit (see build_tree.sh).
COPY --chown=0:0 backend /opt/visitor-display/backend
ENV PYTHONPATH=/opt/visitor-display/backend PYTHONDONTWRITEBYTECODE=1
WORKDIR /opt/visitor-display/backend
