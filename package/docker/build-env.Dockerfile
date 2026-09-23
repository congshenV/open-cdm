# Build environment image for CloudDM CI.
# Carries the full toolchain needed to compile + package + build Docker images:
#   - JDK 17 (gradle 9.5.0 requires JVM 17+)
#   - Node.js 22 + npm (frontend build)
#   - Docker CLI + buildx plugin (package.sh --docker -> buildkit)
#   - git, curl, perl (template rendering), bash
# Jenkins runs the entire chain inside this image, mounting the host docker
# socket + ACR config.json so buildx/tag/push reuse the host daemon & auth.
FROM eclipse-temurin:17-jdk-noble


ARG DEBIAN_FRONTEND=noninteractive
ARG NODE_VERSION=22.22.1

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        ca-certificates curl git perl bash lsb-release gnupg xz-utils \
    && rm -rf /var/lib/apt/lists/*

# Node.js 22.22.1 exact version (matches frontend/AGENTS.md toolchain).
# Node 官方二进制用 x64/arm64 命名，而 dpkg --print-architecture 输出 amd64，需映射架构后再拼 URL。
RUN ARCH=$(dpkg --print-architecture) \
    && case "$ARCH" in \
         amd64) NODE_ARCH="x64" ;; \
         arm64) NODE_ARCH="arm64" ;; \
         *) NODE_ARCH="$ARCH" ;; \
       esac \
    && curl -fsSL "https://nodejs.org/dist/v${NODE_VERSION}/node-v${NODE_VERSION}-linux-${NODE_ARCH}.tar.xz" \
        -o /tmp/node.tar.xz \
    && tar -xJf /tmp/node.tar.xz -C /usr/local --strip-components=1 \
    && rm -f /tmp/node.tar.xz

# Docker CE CLI + buildx plugin (static binaries, no daemon packaged).
RUN curl -fsSL "https://download.docker.com/linux/static/stable/x86_64/docker-27.5.1.tgz" -o /tmp/docker.tgz \
    && tar -xzf /tmp/docker.tgz -C /tmp \
    && install -m 0775 /tmp/docker/docker /usr/local/bin/docker \
    && mkdir -p /usr/local/lib/docker/cli-plugins \
    && curl -fsSL "https://github.com/docker/buildx/releases/download/v0.19.3/buildx-v0.19.3.linux-$(dpkg --print-architecture)" \
        -o /usr/local/lib/docker/cli-plugins/docker-buildx \
    && chmod +x /usr/local/lib/docker/cli-plugins/docker-buildx \
    && rm -rf /tmp/docker /tmp/docker.tgz

ENV PATH="/usr/local/bin:${PATH}"

WORKDIR /workspace

CMD ["bash"]
