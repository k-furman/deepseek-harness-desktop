# GitHub Actions

## Подключение репозитория

Пайплайны готовы для GitHub.com. Добавьте исходники в GitHub-репозиторий вместе с
`.github/`, `.node-version`, `rust-toolchain.toml`, обоими lock-файлами, иконками
и `scripts/ci/`: автономный аудит Tauri сохранён в `scripts/ci/tauri-audit/`.
Сгенерированные разрешения Tauri создаёт `src-tauri/build.rs` при сборке.
`node_modules`, `.tools`, `.cache`, `artifacts`, `dist`, `src-tauri/target` и локальные
инструкции/навыки агента исключены через `.gitignore`.

1. В **Settings → Actions → General** включите Actions и разрешите официальные
   actions из организации `actions`. Они закреплены по полному SHA коммита.
2. Откройте **Actions → CI → Run workflow** для первой проверки либо отправьте
   коммит/PR. Название основной ветки не зашито в конфигурацию.
3. После первого успешного запуска в ruleset основной ветки добавьте обязательную
   проверку **CI required**. Она требует успешных проверок и всех трёх нативных сборок.
   Merge queue поддерживается событием `merge_group`.

Дополнительные secrets для текущей поставки не нужны. GitHub выдаёт `GITHUB_TOKEN`
автоматически. Проверки и сборки используют `contents: read`; только отдельный
шаг создания черновика релиза получает `contents: write`. Checkout не сохраняет
учётные данные Git. Fork PR не получает секреты и не запускает создание релиза.
Если политика организации запрещает запись workflow-токеном, её нужно разрешить
для release job на уровне организации; личный PAT не требуется.

## Workflows

| Файл | Запуск | Результат |
| --- | --- | --- |
| `.github/workflows/ci.yml` | Push в любую ветку, PR, merge queue, вручную | Проверки, три набора пакетов и итоговая проверка `CI required` |
| `.github/workflows/build.yml` | Общий reusable workflow для CI и релизов | `macos-15` arm64, `ubuntu-22.04` x86_64 и `windows-2022` x64 |
| `.github/workflows/release.yml` | Push тега `v*` | Те же проверки и сборки, затем черновик GitHub Release |

Версии инструментов закреплены: Node в `.node-version`, Rust с Clippy/rustfmt
в `rust-toolchain.toml`. npm устанавливается через `npm ci`; Cargo проверяется
и собирается с `--locked`. Docker использует те же версии в `scripts/Dockerfile.linux`;
при смене инструментов обновляйте их там тоже. Кэшируются npm/Cargo downloads;
Rust компилируется заново, чтобы разрешения и пакеты формировались из текущего checkout.
Dependabot раз в неделю предлагает PR для обновления SHA GitHub Actions.

Source checks проверяют согласованность версий, код подготовки релиза, workflows
(actionlint с проверкой SHA-256), конфигурацию/разрешения Tauri, ESLint, Vitest,
TypeScript и production-сборку Vite. Аудит допускает одно известное предупреждение:
окна создаются в Rust, поэтому статический список `app.windows` пуст.

Все три платформы проходят Rust fmt, Clippy с `-D warnings` и Rust-тесты. Linux также
проверяет GTK-диалог, установленный DEB и нативный интерфейс через Xvfb/WebKitWebDriver:
token → cookie, WebSocket, повторное подключение, сетевые ошибки, отмену, изоляцию IPC,
меню, языки, закреплённую оболочку, загрузку/скачивание и буфер обмена. AppImage
проверяется и как извлечённый AppRun, и запуском исходного файла с
`APPIMAGE_EXTRACT_AND_RUN=1` на нативном x86_64 runner.

Сборка macOS проверяет архитектуру arm64, минимальную версию macOS 14 в Info.plist,
подпись `.app` через `codesign --verify` и целостность DMG через `hdiutil verify`.
Используется **ad-hoc подпись** (`signingIdentity: "-"`): сертификат Apple Developer ID
и notarization пока не настроены. Ad-hoc подпись не подтверждает издателя и не
отменяет подтверждение запуска скачанного приложения в настройках безопасности macOS.

Windows собирается нативно с MSVC на `windows-2022`, где установлены Visual Studio
Build Tools, NSIS и WiX 3. CI проверяет синтаксис PowerShell-скриптов, PE x64
приложения, действительные версию и архитектуру MSI. 32-битный NSIS bootstrapper
допустим: приложение внутри него остаётся x64. Затем на одноразовом runner оба
установщика по очереди устанавливаются в каталоги с пробелами, приложение создаёт
окно и завершается при его закрытии, после чего выполняется удаление.
Эта проверка не подтверждает отрисовку формы, меню, WebView2-авторизацию или файловые
диалоги: для Windows они остаются ручной проверкой по [verification.md](verification.md).
Логи MSI установки/удаления прикладываются к diagnostics. Windows Authenticode
не настроен; дополнительных signing secrets не требуется. NSIS предлагает
English/Русский и установку для текущего пользователя; MSI имеет английский UI.
Встроенный bootstrapper устанавливает WebView2 через интернет при необходимости.

## Артефакты

В **Actions → выбранный run → Artifacts** доступны:

- `packages-macos-arm64`: DMG, `.app.tar.gz`, `build-macos-arm64.json`, `SHA256SUMS-macos-arm64`;
- `packages-linux-x86_64`: DEB, AppImage, `build-linux-x86_64.json`, `SHA256SUMS-linux-x86_64`;
- `packages-windows-x86_64`: NSIS `.exe`, MSI, `build-windows-x86_64.json`, `SHA256SUMS-windows-x86_64`;
- `diagnostics-*`: логи сборки/Rust и снимки Linux-тестов, в том числе при ошибке.

Пакеты сохраняются 14 дней, диагностика — 7. В metadata записываются версия,
коммит, номер run, платформа, минимальная ОС и закреплённые инструменты.
`.app` помещается в tar.gz, чтобы перенос через Actions сохранил исполняемые права.
После извлечения Actions artifact AppImage сделайте исполняемым:

```sh
chmod +x DeepSeek-Harness-Desktop_0.1.0_linux-x86_64.AppImage
```

На Linux проверьте файлы через `sha256sum -c SHA256SUMS-linux-x86_64`, на macOS —
`shasum -a 256 -c SHA256SUMS-macos-arm64`. Архив приложения извлекается командой
`tar -xzf DeepSeek-Harness-Desktop_0.1.0_macos-arm64.app.tar.gz`.

На Windows хеш файла проверяется командой PowerShell
`Get-FileHash .\DeepSeek-Harness-Desktop_0.1.0_windows-x86_64-setup.exe -Algorithm SHA256`;
сравните его с записью в `SHA256SUMS-windows-x86_64`.

## Подготовка версии и релиз

Перед тегом версии должны совпадать в `package.json`, двух полях корня
`package-lock.json`, `src-tauri/Cargo.toml`, пакете приложения в
`src-tauri/Cargo.lock` и `src-tauri/tauri.conf.json`.

Для следующей версии, например `0.2.0`:

1. Выполните `npm version 0.2.0 --no-git-tag-version`: обновятся npm manifest/lock.
2. Установите `version = "0.2.0"` в `[package]` Cargo.toml и `"version": "0.2.0"`
   в tauri.conf.json. Выполните
   `node scripts/with-rust.mjs cargo check --manifest-path src-tauri/Cargo.toml`,
   чтобы обновить версию приложения в Cargo.lock.
3. Выполните `npm run ci:check` и `npm run native:check`, закоммитьте изменения,
   дождитесь успешного CI для этого коммита.
4. Создайте и отправьте тег:

```sh
git tag -a v0.2.0 -m "DeepSeek Harness Desktop 0.2.0"
git push origin v0.2.0
```

Тег обязан точно совпадать с версией (`v0.2.0`); несовпадение останавливает workflow
до нативной сборки. Поддерживаются prerelease-версии, например `0.2.0-rc.1`, с тегом
`v0.2.0-rc.1`. В ruleset тегов `v*` ограничьте создание/изменение тегов релиза
уполномоченными участниками проекта.

Release job скачивает **только пакеты своего run**, проверяет полный набор файлов,
контрольные суммы, версию, все три платформы и исходный коммит. Полный набор содержит
12 файлов: по два пакета, metadata и SHA256SUMS на платформу. Отсутствие Windows
останавливает создание релиза. Затем создаётся **черновик**.
Повторный запуск обновляет файлы существующего черновика; уже опубликованный релиз
workflow менять откажется. Публикация выполняется вручную после проверки пакетов.

Перед публикацией проверьте GUI macOS и Windows, подключение к реальному DeepSeek Harness,
установку/запуск на минимальной ОС и нужных рабочих столах Linux. Xvfb проверяет X11;
он не подтверждает Wayland, Debian 12 или поведение окон macOS. Текущие результаты
сборок и ручной проверки ведутся отдельно в [verification.md](verification.md).

## Локальная проверка пайплайнов

```sh
npm ci
npm run ci:check
npm run ci:workflows
npm run native:check
bash scripts/ci/build-desktop.sh macos
# Linux на Mac: npm run linux:build
```

`ci:workflows` скачивает закреплённый actionlint с GitHub и требует доступа в интернет.
Общий сборщик требует пустой `artifacts/release-<платформа>/` для нового набора:
перед повторной локальной сборкой переместите предыдущий каталог, если он нужен.
Linux CI устанавливает собственный DEB на одноразовый runner; для локального
использования на Mac предусмотрен Docker. Реальные URL/токены Harness в CI не нужны:
проверки используют только публичную тестовую авторизацию fixture.

На Windows из PowerShell: `npm ci`, `npm run ci:check`, `npm run native:check`,
`npm run windows:build`. Команда упаковки сама не устанавливает пакеты.
Если Windows не разрешает создание symlink без повышенных прав, только тест
symlink явно помечается skipped; в Linux Source checks он выполняется всегда.
В чистой Windows VM дополнительно можно выполнить
`powershell -NoProfile -ExecutionPolicy Bypass -File scripts/ci/build-windows.ps1 -VerifyInstallers`.
Этот флаг предназначен для одноразовой среды: он устанавливает/удаляет приложение
и оставляет его профиль в стандартном AppData, как обычная установка.

## Источники конфигурации

- [Tauri: GitHub pipelines](https://v2.tauri.app/distribute/pipelines/github/) — нативные сборки по платформам.
- [GitHub: hosted runners](https://docs.github.com/en/actions/reference/runners/github-hosted-runners) — нативные runners трёх платформ.
- [Windows runner image](https://github.com/actions/runner-images/blob/main/images/windows/Windows2022-Readme.md) — инструменты `windows-2022`.
- [Tauri: Windows installers](https://v2.tauri.app/distribute/windows-installer/) — NSIS, WiX, языки и WebView2.
- [Tauri: macOS ad-hoc signing](https://v2.tauri.app/distribute/sign/macos/#ad-hoc-signing) — подпись без Apple identity.
- [GitHub: upload-artifact](https://github.com/actions/upload-artifact#permission-loss) — сохранение Unix-прав через архив.
- [actionlint](https://github.com/rhysd/actionlint) — статическая проверка workflows.
