#!/usr/bin/env bash
set -euo pipefail
task_root="$(cd "$(dirname "$0")/.." && pwd)"
mkdir -p "$task_root/artifacts/linux"
docker build --platform linux/amd64 -f "$task_root/scripts/Dockerfile.linux" -t dsh-desktop-builder "$task_root"
docker run --rm --platform linux/amd64 \
  --mount "type=bind,src=$task_root/artifacts/linux,dst=/workspace/artifacts/linux" \
  --mount type=volume,src=dsh-linux-target,dst=/workspace/src-tauri/target \
  --mount type=volume,src=dsh-linux-cargo,dst=/root/.cargo \
  dsh-desktop-builder
