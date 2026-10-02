#!/usr/bin/env bash
# Used by GitHub runners and the local Linux builder; never uses server credentials.
set -euo pipefail
task_root="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$task_root"
task_platform="${1:?Expected macos or linux}"

case "$task_platform" in
  macos)
    test "$(uname -s)" = Darwin
    test "$(uname -m)" = arm64
    export MACOSX_DEPLOYMENT_TARGET=14.0
    npm run desktop:build -- --ci --config src-tauri/tauri.macos.conf.json --bundles app,dmg -- --locked
    ;;
  linux)
    test "$(uname -s)" = Linux
    test "$(uname -m)" = x86_64
    export APPIMAGE_EXTRACT_AND_RUN=1
    timeout 60s dbus-run-session -- xvfb-run -a bash scripts/with-rust.sh cargo test \
      --locked --manifest-path src-tauri/Cargo.toml save_dialog_cancels_inside_the_gtk_event_loop \
      -- --ignored --test-threads=1
    npm run desktop:build -- --ci --config src-tauri/tauri.linux.conf.json --bundles deb -- --locked
    python3 scripts/prepare-appimage.py
    npm run tauri -- bundle --ci --config src-tauri/tauri.linux.conf.json --bundles appimage
    mkdir -p artifacts/linux
    cp src-tauri/target/release/bundle/deb/*.deb src-tauri/target/release/bundle/appimage/*.AppImage artifacts/linux/
    if [ "$(id -u)" = 0 ]; then
      dpkg -i src-tauri/target/release/bundle/deb/*.deb
    else
      sudo dpkg -i src-tauri/target/release/bundle/deb/*.deb
    fi
    export DSH_TEST_BINARY=/usr/bin/deepseek-harness-desktop
    timeout 180s dbus-run-session -- xvfb-run -a python3 tests/native_linux.py
    timeout 180s dbus-run-session -- xvfb-run -a python3 tests/language_linux.py
    timeout 90s dbus-run-session -- xvfb-run -a python3 tests/download_linux.py
    timeout 120s python3 tests/appimage_linux.py
    if [ "${DSH_APPIMAGE_RUNTIME_TEST:-0}" = 1 ]; then
      timeout 120s python3 tests/appimage_linux.py --runtime
    fi
    (cd artifacts/linux && sha256sum ./*.deb ./*.AppImage > SHA256SUMS)
    ;;
  *) echo 'Expected macos or linux' >&2; exit 2 ;;
esac

python3 scripts/ci/release.py collect --platform "$task_platform"
