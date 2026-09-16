#!/bin/bash
# ci-run.sh — Run the full CloudDM build chain inside the build-env image.
# Entry point for the build-env container on CI. Expects the repo mounted at
# /workspace and env vars set by Jenkins:
#   BUILD_ARCH, BUILD_VERSION, IMAGE_TAG, ACR, NAMESPACE, SERVICES
# It compiles, packages, builds docker images, then tags & pushes to ACR.
set -euo pipefail

BUILD_ARCH="${BUILD_ARCH:-x86_64}"
ACR="${ACR:-}"
NAMESPACE="${NAMESPACE:-}"
SERVICES="${SERVICES:-console sidecar}"

: "${BUILD_VERSION:?BUILD_VERSION is required}"
: "${IMAGE_TAG:?IMAGE_TAG is required}"
[ -n "$ACR" ] || { echo "error: ACR is required"; exit 1; }
[ -n "$NAMESPACE" ] || { echo "error: NAMESPACE is required"; exit 1; }

echo "build-env toolchain:"
echo "  java:   $(java -version 2>&1 | head -1)"
echo "  gradle: $(grep distributionUrl /workspace/backend/gradle/wrapper/gradle-wrapper.properties)"
echo "  node:   $(node -v)"
echo "  npm:    $(npm -v)"
echo "  docker: $(docker --version)"
echo "  buildx: $(docker buildx version)"

cd /workspace/package
./package.sh --build
./package.sh --docker "$BUILD_ARCH"

for svc in $SERVICES; do
    src="clougence/cgdm-${svc}:${BUILD_ARCH}-${BUILD_VERSION}"
    dst="${ACR}/${NAMESPACE}/cgdm-${svc}:${IMAGE_TAG}"
    echo "Tagging  ${src} -> ${dst}"
    docker tag "$src" "$dst"
    echo "Pushing  ${dst}"
    docker push "$dst"
    echo "Pushed:  ${dst}"
done
