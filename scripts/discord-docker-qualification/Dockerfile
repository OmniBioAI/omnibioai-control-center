ARG BASE_IMAGE=obai-control-center:f37ce8c952f9
FROM ${BASE_IMAGE}

ARG CANDIDATE_REVISION
ARG SOURCE_TREE_SHA256
ARG QUAL_RUN_ID
LABEL org.opencontainers.image.source="https://github.com/OmniBioAI/omnibioai-control-center" \
      org.opencontainers.image.revision="${CANDIDATE_REVISION}" \
      io.omnibioai.discord-qualification.source-tree-sha256="${SOURCE_TREE_SHA256}" \
      io.omnibioai.workstream="OMNIBIOAI_DISCORD_DOCKER_QUALIFICATION_INFRASTRUCTURE_V1" \
      io.omnibioai.run-id="${QUAL_RUN_ID}" \
      io.omnibioai.disposable="true"

USER root
COPY backend/src/ /app/src/
COPY scripts/discord-docker-qualification/ /opt/discord-qualification/
ENV PYTHONPATH=/app/src:/opt/discord-qualification PYTHONUNBUFFERED=1
USER 10001:10001
