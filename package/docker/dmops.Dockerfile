# Multi-arch Dockerfile for the CloudDM dmops service.
# dmops is a standalone Python service: it only needs the source tree, the
# pinned requirements and environment variables, no conf volume and no init script.
# Build context expected layout:
#   <ctx>/cgdm-dmops.tar.gz            (archive root: dmops/)
#   <ctx>/shared/dmops/healthcheck.sh
# Point BASE_IMAGE at an internal mirror when docker.io is not reachable.
ARG BASE_IMAGE=python:3.12-slim-bookworm
FROM ${BASE_IMAGE}

ARG DEBIAN_FRONTEND=noninteractive
# Override for networks that cannot reach pypi.org, e.g.
#   --build-arg PIP_INDEX_URL=https://mirrors.aliyun.com/pypi/simple/
ARG PIP_INDEX_URL=https://pypi.org/simple

RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates tzdata \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd -r dmops \
    && useradd -r -g dmops -d /app -s /usr/sbin/nologin dmops

ENV TZ=Asia/Shanghai \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    DMOPS_HOST=0.0.0.0 \
    DMOPS_PORT=8080 \
    DMOPS_DEBUG=false \
    DMOPS_LOG_LEVEL=INFO \
    DMOPS_IDENTITY_VERIFY_ENABLED=true

WORKDIR /app
ADD cgdm-dmops.tar.gz /app/
RUN pip install --no-cache-dir --index-url "$PIP_INDEX_URL" -r /app/dmops/requirements.txt \
    && chown -R dmops:dmops /app

COPY shared/dmops/healthcheck.sh /usr/local/bin/healthcheck.sh
RUN chmod +x /usr/local/bin/healthcheck.sh

USER dmops
WORKDIR /app/dmops

# dmops listens on DMOPS_PORT, it is only reachable through the console proxy.
EXPOSE 8080

# every /v1/** request needs the forwarded identity signature, the healthcheck
# computes one from the same secret instead of calling an unauthenticated path.
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD ["/usr/local/bin/healthcheck.sh"]

# instance sync calls the Aliyun OpenAPI, which is far slower than gunicorn's
# default 30s worker timeout, so the timeout is raised and threads are used
# instead of relying on more sync workers.
# -w 1: the backup-drill worker thread lives inside create_app(); a single
# process keeps exactly one drill worker and makes the "global concurrency = 1"
# guarantee race-free (docs/backup-drill-design.md §8). IO concurrency comes
# from gthread, not worker count.
CMD ["gunicorn", "-w", "1", "-k", "gthread", "--threads", "8", "--timeout", "180", "--graceful-timeout", "30", "--access-logfile", "-", "--error-logfile", "-", "-b", "0.0.0.0:8080", "main:create_app()"]
