# The caller verifies this local tag resolves to manifest.legacy_image before building.
# Build with --pull=false --network=none; no dependency install or migration is part of this image.
ARG LEGACY_IMAGE
FROM ${LEGACY_IMAGE}
COPY overlay/app/ /app/app/
COPY verification/ /opt/admin-pipeline-release/
