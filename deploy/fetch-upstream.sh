#!/usr/bin/env bash
# Check out frappe_docker at the pinned tag. Its resources/ files are the named build context `fd`.
set -euo pipefail
cd "$(dirname "$0")"
TAG=$(sed -n 's/^BUILD_FRAPPE_DOCKER_TAG=//p' versions.env)
DIR=.upstream/frappe_docker
if [ -d "$DIR/.git" ] && [ "$(git -C "$DIR" describe --tags --exact-match 2>/dev/null)" = "$TAG" ]; then
  exit 0
fi
rm -rf "$DIR"
mkdir -p .upstream
git clone --quiet --depth 1 --branch "$TAG" https://github.com/frappe/frappe_docker "$DIR"
