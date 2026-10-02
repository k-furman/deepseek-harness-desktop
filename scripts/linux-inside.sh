#!/usr/bin/env bash
set -euo pipefail
task_root="$(cd "$(dirname "$0")/.." && pwd)"
cd "$task_root"
npm ci
npm run check
npm run native:check
bash scripts/ci/build-desktop.sh linux
