#!/bin/bash
# ci-run-docker.sh — Launch the build-env container and run the full CI build
# chain inside it (see ci-run.sh). Mounts the host docker socket and ACR
# config.json so package.sh --docker / docker push reuse the host daemon + creds.
# Expected env: WORKSPACE, BUILD_ARCH, BUILD_VERSION, IMAGE_TAG, ACR, NAMESPACE,
# SERVICES, BUILD_IMAGE.
set -euo pipefail

WORKSPACE="${WORKSPACE:?WORKSPACE is required}"
BUILD_IMAGE="${BUILD_IMAGE:-cgdm-build-env:ci}"

docker run --rm \
    -v "${WORKSPACE}:/workspace" \
    -v "/var/run/docker.sock:/var/run/docker.sock" \
    -v "$HOME/.docker/config.json:/root/.docker/config.json" \
    -w "/workspace" \
    -e "BUILD_ARCH=${BUILD_ARCH:-x86_64}" \
    -e "BUILD_VERSION=${BUILD_VERSION}" \
    -e "IMAGE_TAG=${IMAGE_TAG}" \
    -e "ACR=${ACR}" \
    -e "NAMESPACE=${NAMESPACE}" \
    -e "SERVICES=${SERVICES:-console sidecar}" \
    "${BUILD_IMAGE}" \
    bash "/workspace/package/docker/ci-run.sh"
