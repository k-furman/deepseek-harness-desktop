# Verification — 2026-10-02

## Optimization follow-up

The optimized macOS arm64 release executable is 6,033,232 bytes (previously
7,900,320); the signed `.app` is 6,095,341 bytes (previously 7,951,581), a 23.34%
reduction. Local WebView files total 18,242 bytes instead of 20,032. Measurements
compare two builds on the same host and toolchain; they do not measure RSS/CPU.
See [optimization.md](optimization.md) for the component review and decisions.

- Source gates pass: 20 release tests, 2 auditor tests, ESLint, 21 frontend tests,
  TypeScript and Vite. Both Tauri auditors report zero failures and the known
  advisory about windows being created in Rust. Actionlint passes.
- macOS: rustfmt, Clippy with warnings denied, 19 Rust tests, release `.app` build,
  arm64 inspection and strict signature verification pass. Computer Use times out
  when selecting the exact newly built app path; native GUI remains unverified.
- Linux Ubuntu 22.04 x86_64 in Docker emulation: frontend checks, formatting,
  Clippy, 19 Rust tests and the separate GTK Save/Cancel test pass. DEB and
  AppImage build. The full native fixture suite passes on the release binary
  and again on the installed DEB, including external links without remote IPC.
  Language/preferences, ordinary downloads and extracted packaged AppImage
  startup/authentication/Save/Cancel/content tests pass.
- The initial Linux build command stopped at wheel input. The test now moves
  away and waits for WebKit's actual panel hover before sending the wheel;
  external `_blank` links use trusted WebDriver clicks. Final native suites ran
  in separate disposable containers on the same build. The complete build
  command was not rerun after this test-only repair.
- Existing GTK accelerator and missing AT-SPI warnings remain in the container.
  Direct AppImage runtime/FUSE on native x86_64, Wayland and Debian 12 remain
  unverified. Windows has no available host and remains unverified.

Final native logs and before/after JSON are local, ignored artifacts in
`artifacts/optimization/`. Packages, screenshots and SHA-256 are in
`artifacts/linux/`. The sections below describe the earlier preparation checks;
their test counts and macOS debug bundle are historical.

## Automated source checks

- `npm ci --cache .cache/npm --offline` restores dependencies from `package-lock.json`.
- `npm run ci:check` passes: version alignment, 20 release tests, two auditor
  regression tests, ESLint, 18 frontend tests, TypeScript and the production Vite build.
- The source checks also pass in a copy exported from the Git index without local
  agent skills or toolchains. That copy reuses the installed npm dependencies.
- `npm run ci:workflows` passes actionlint 1.7.12 after verifying its SHA-256.
- The Tauri auditor reports zero failures and one known advisory: windows are
  created in Rust, so the static `app.windows` list is empty.
- The network diagnostic is connected to the managed `Probe` instance. Regression
  tests cover cookie path scopes across redirects, external redirect refusal,
  HTTP error categories, transport checks without authorization and a deadline
  that includes reading WebView cookies.

These checks run locally. GitHub-hosted jobs and release API calls have not run
during this preparation.

## Application icon

- The SVG combines the unchanged official DeepSeek whale path with a desktop
  monitor. Its pinned upstream source and MIT license are preserved in `assets/`.
- `npm run icons` regenerates exactly seven desktop assets and removes temporary
  mobile/Windows Store output. PNG and ICO bytes and every ICNS representation
  are reproducible; ICNS chunk ordering can differ between Tauri CLI runs.
- All PNG sizes, ICO frames and ICNS representations decode correctly and retain
  transparent padding. The 32, 64, 128, 256 and 512 px artwork was inspected visually.
- The rebuilt macOS debug `.app` references the new ICNS in `CFBundleIconFile`;
  its bundled bytes match the source and strict code-signature verification passes.
- The rebuilt Linux DEB contains matching 32, 128 and 256 px PNGs (the HiDPI
  directory is `256x256@2`). A native launch under Xvfb exposes the new 32 px
  artwork in the window's `_NET_WM_ICON` property, with matching RGBA pixels.
- Windows ICO frames were decoded, but native Windows display remains unverified.

The subsequent background-only revision to navy (`#09162F`) was checked in the
regenerated PNG, ICNS and ICO assets. Native package/window checks above used the
preceding blue background.

## macOS

- `npm run native:check` passes formatting, Clippy with warnings denied and 16 Rust tests.
- A debug `.app` builds with the macOS configuration and ad-hoc signing:
  `npm run tauri -- build --debug --ci --config src-tauri/tauri.macos.conf.json --bundles app -- --locked`.
- `codesign --verify --deep --strict` passes; the bundled executable is arm64.
- Computer-use automation times out. Native window rendering, menus, Settings,
  authenticated WebView operation, file dialogs and clipboard remain manual checks.
- Developer ID signing, notarization and a new release DMG were not tested in this run.

## Linux

- Ubuntu 22.04 x86_64 runs in Docker under emulation on Apple Silicon.
- Frontend checks, Rust formatting, Clippy and 16 Rust tests pass.
- The separate GTK Save/Cancel regression passes under Xvfb.
- Release DEB and AppImage packages build; the DEB installs successfully.
- The full native fixture suite passes on the compiled release binary: token/cookie,
  API/WebSocket, IPC denial, upload/download, clipboard, shortcuts, zoom, scrolling,
  reload, session expiry/reset/retry, cookie persistence, network/403/TLS errors,
  cancellation and sanitized settings.
- The first installed-DEB run timed out during wheel input. The X11 test now waits
  for window focus and pointer movement before sending wheel events; the complete
  suite passes on rerun with the same build.
- Language/preferences tests pass, including live English/Russian switching,
  native menus and dialogs, saved overrides, System fallback and session retention.
- Ordinary WebView downloads and the extracted packaged AppImage AppRun pass
  startup, authentication, native Save/Cancel and downloaded-content checks.
- Direct AppImage runtime/FUSE launch on native x86_64, Wayland and Debian 12
  were not tested. GTK menu accelerator and missing AT-SPI warnings occur in
  the container; the corresponding native menu/dialog tests pass.

## Windows

No Windows host is available. Compilation, generated installers, installation,
upgrade, WebView2 rendering and native UI remain unverified in this run.
The GitHub matrix includes native Windows build and installer lifecycle checks.

## Repository hygiene

Build output, packaged applications, caches, logs and screenshots are local
artifacts excluded by `.gitignore`; they are not part of the source repository.
Local agent instructions and skills are excluded as well. CI uses the vendored
standalone auditor in `scripts/ci/tauri-audit/`, with its upstream license.

Toolchains are pinned by `.node-version`, `rust-toolchain.toml` and both lock-files.
Setup and release instructions: [github-actions.md](github-actions.md).

### Windows manual acceptance

1. Install the NSIS package on a clean Windows 10/11 x64 machine, then separately
   test MSI on a clean VM. Verify WebView2 bootstrapper installation when the runtime
   is absent. Test install paths with spaces and a non-ASCII Windows username.
2. Launch without a console window; confirm the local form renders in WebView2.
   Connect to the fixture, then the real Harness URL. Check token/cookie, WebSocket,
   reconnect/restart, expired authorization, TLS errors and IPC denial.
3. Check Ctrl+L/R, Ctrl+comma, F11, Edit/zoom menus, English/Russian/System settings,
   fixed outer viewport, inner scrolling, theme, file picker/drop, download/cancel,
   clipboard and external links. Confirm a second launch focuses the first instance
   and closing Settings keeps the main window alive; closing the main window exits.
4. Upgrade from a previous package and verify the clean URL, language and cookie
   persist. Uninstall and confirm the binary/shortcuts disappear; retaining or
   explicitly removing user data follows the selected installer option.

## Manual acceptance

1. Open the `.app` or install it from the `.dmg`. Paste the full launch link issued
   by the existing container and connect. Confirm the original Harness interface.
2. Scroll over the header and reach both ends of a long chat with the trackpad.
   The outer shell must remain still; messages and sidebar lists must scroll
   independently. Resize the window, change zoom and reload: the shell should
   continue to fill the window, with the composer visible.
3. Use Cmd+L, then connect with the clean remembered address. Quit/relaunch and
   confirm the address is proposed without automatic connection; the cookie works.
4. Try Cmd+R, zoom, Edit operations, fullscreen, close/Dock reopen and explicit Quit.
5. Select/drag a file, download a file through Save, and open an external link.
6. Reset the session and reconnect without a token: authorization should be required.
7. Use the fixture's **Expire session** and **Check IPC isolation** buttons: retry
   should work, and every listed native command should be denied.
8. Open Settings through the menu, Cmd/Ctrl+, or the connection screen's Settings
   button. Select English, Русский, then System language. Confirm immediate changes
   in labels, errors, menus and application-owned dialogs, without reconnecting.
   Close Settings and reopen it; quit/relaunch to confirm the saved choice.
9. With System selected, confirm Russian/English follows the primary system
   language and another system language uses English. macOS-owned panel controls
   follow the OS; the remote Harness website manages its own language.

## Cross-platform acceptance matrix

- Clean launch: URL form, Enter, native text editing, keyboard focus, system theme.
- Valid fixture token: redirect removes token; API and WebSocket say authenticated.
- Outer mount stays within the viewport; chat/sidebar/code scroll independently,
  including at boundaries, after resize, zoom, navigation and reload.
- Relaunch: clean remembered address, explicit Connect, retained browser cookie.
- Invalid/expired token: authorization message and a working retry.
- Unavailable server: bounded timeout/error; cancel/replacement ignores old callbacks.
- Menu: Cmd/Ctrl+L, Cmd/Ctrl+R, zoom, fullscreen, Edit, close/reopen and explicit Quit.
- Preferences: Cmd/Ctrl+comma, live Russian/English, System fallback, saved override,
  connected session retained, secondary Close keeps the main window alive.
- File selection, HTML drag/drop, Save dialog, successful downloaded content.
- External HTTP(S) opens the default browser; unsupported schemes are denied.
- Fixture IPC button: custom commands and plugin commands all denied.
- Real server localhost:3000: authenticated interface and normal Harness operation.
- Linux x86_64: native window/menu plus installable DEB/AppImage on minimum distro.

Browser-only checks do not establish native behavior. macOS, Linux and Windows results are separate.
