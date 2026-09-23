#!/bin/bash
# ci-run-docker.sh — Launch the build-env container and run the full CI build
# chain inside it (see ci-run.sh).
#
# The agent is a Docker-in-Docker (dind) container: `docker run` talks to a
# shared OUTER daemon, which resolves bind-mount source paths on the OUTER
# host, NOT inside the agent. The agent's real workspace path (e.g.
# /home/jenkins/agent/workspace/<job>) does not exist on that outer host, so a
# `-v ${WORKSPACE}:/workspace` mount silently becomes empty and ci-run.sh is
# never found.
#
# To avoid host-path resolution entirely we:
#   1. create a long-lived container (only the docker socket is bind-mounted,
#      same path in both namespaces),
#   2. stream the workspace in via `docker exec -i tar`,
#   3. copy the ACR creds into the container with `docker cp`,
#   4. exec ci-run.sh inside it. Docker buildx/tag/push reuse the shared daemon.
#
# Expected env: WORKSPACE, BUILD_ARCH, BUILD_VERSION, IMAGE_TAG, ACR, NAMESPACE,
# SERVICES, BUILD_IMAGE.
set -euo pipefail

WORKSPACE="${WORKSPACE:?WORKSPACE is required}"
BUILD_IMAGE="${BUILD_IMAGE:-cgdm-build-env:ci}"

CID="$(docker run -d \
    -v /var/run/docker.sock:/var/run/docker.sock \
    "${BUILD_IMAGE}" \
    sleep infinity)"

cleanup() {
    docker rm -f "${CID}" >/dev/null 2>&1 || true
}
trap cleanup EXIT

# Workspace in: stream via stdin so no host path is bind-mounted.
docker exec -i "${CID}" bash -c 'mkdir -p /workspace && tar -xf - -C /workspace' \
    < <(tar -C "${WORKSPACE}" -cf - .)

# ACR auth in: copy, not mount (its host path is also unresolved under dind).
if [ -f "${HOME}/.docker/config.json" ]; then
    docker cp "${HOME}/.docker/config.json" "${CID}:/root/.docker/config.json"
fi

# Build vars in: docker run -e is gone (we exec), so pass them on exec. ci-run.sh
# requires BUILD_VERSION, IMAGE_TAG, ACR, NAMESPACE; the rest are optional.
docker exec \
    -e "BUILD_ARCH=${BUILD_ARCH:-x86_64}" \
    -e "BUILD_VERSION=${BUILD_VERSION}" \
    -e "IMAGE_TAG=${IMAGE_TAG}" \
    -e "ACR=${ACR}" \
    -e "NAMESPACE=${NAMESPACE}" \
    -e "SERVICES=${SERVICES:-console sidecar}" \
    "${CID}" \
    bash /workspace/package/docker/ci-run.sh
