#!/usr/bin/env bash
set -euo pipefail
task_root="$(cd "$(dirname "$0")/.." && pwd)"
exec node "$task_root/scripts/with-rust.mjs" "$@"
