# Desktop lifecycle and trust boundaries

Tauri 2 / Rust owns windows, settings, native menus and the network diagnostic.
The bundled TypeScript connection screen starts/cancels a connection, reads its state
and opens the bundled settings window. The settings window can only read its
preferences, select a supported language and close itself; it cannot connect to a server.
Remote content has no capability, and custom commands are included in AppManifest.
Every command also checks the caller's window label. No iframe, proxy or API rewrite.

Only one primary window is visible. The local window remains available while the
remote window authenticates; success switches visibility. Switching servers destroys
the old remote window and unregisters its GTK menu before the native address can be
reused. Each connection has a unique identity so old callbacks and
timeouts cannot affect a newer connection. A reload has its own verification cycle.
Each connection or reload has a 60-second overall deadline.
Each cycle also owns a cancellation sender. Completion, Cancel, replacement and
download navigation drop that sender, releasing pending HTTP verification and the
deadline worker. Transport diagnosis and the overall deadline share one task.
An already running blocking OS cookie read finishes normally; its cancelled
verification cannot change a newer session. These workers live in `connection.rs`.
Each Linux server window owns its menu tree and GTK accelerator group; macOS uses
one application-wide menu.
Windows uses a native window menu and WebView2. The bundled UI is permitted to
navigate only within `http://tauri.localhost` (the default custom-protocol mapping);
macOS/Linux use `tauri://localhost`. Userinfo, non-default ports and lookalike hosts
are rejected. The development URL is allowed only in debug builds. These navigation
rules do not grant IPC to the server window; its label still has no capability.
Settings is a separate secondary window. Closing it destroys only that window and
unregisters its own GTK menu; it does not close, hide or disconnect the primary window.

The launch URL is opened in WebView, which receives the server cookie itself.
After the page finishes loading, Rust copies only matching cookies into a
same-origin diagnostic request. Each allowed redirect reads cookies for its new
URL, preserving cookie path scopes. Redirects cannot forward cookies to another origin.
Transport checks and verification share a lazily initialized HTTP client; loading
the system TLS roots runs outside the async executor.
A parallel request to the clean address checks transport only, without tokens or
cookies. It distinguishes TLS/network errors even when WebView emits no finish event;
HTTP authorization is decided by the later request using the WebView session.
Neither the launch token nor cookie is logged or stored in application settings.
Browser storage persists in a dedicated WebView profile; Reset Session clears it.
macOS permits HTTP in web content because users explicitly connect to HTTP servers;
HTTPS certificate validation remains enabled. The WebView-specific ATS exception is
documented by [Apple](https://developer.apple.com/documentation/bundleresources/information-property-list/nsapptransportsecurity/nsallowsarbitraryloadsinwebcontent).

## Affordances

| Surface | Behavior | Preserved state |
| --- | --- | --- |
| Connection form | Labelled text input, Enter connects, visible keyboard focus, live status, Cancel | Last URL without query/fragment or credentials |
| Remote interface | Fixed shell filling the window, scrolling inside panels, browser text editing/paste, HTML file drop/picker, native download dialog | Browser cookies and site storage |
| Menus | Connection Cmd/Ctrl+L, Reload Cmd/Ctrl+R, zoom, standard Edit/Window/Quit | Window dimensions |
| Settings | Cmd/Ctrl+comma, language selector, Close/Escape | `system`, `en` or `ru` |
| Close | macOS hides; Dock/Window/second launch reopens. Linux/Windows exit. Explicit Quit exits all platforms | Last connection and browser profile |

Downloads use Cocoa dialogs on macOS, Windows native dialogs and GTK dialogs on Linux. The Linux save/error
dialogs do not require an XDG Desktop Portal service.
Linux replaces Wry's default download handlers on the persistent WebKitGTK context
with one native handler whenever a server view is created. Individual signal IDs are
removed using the API available in Ubuntu 22.04's GLib 2.72;
each download uses its own error state and the window that initiated it. Cancelling
Save does not poison later downloads or retain a destroyed server window.

## Remote viewport

The server WebView installs `desktop_shell.js` at document start, only in its main
frame and only at the selected server origin. Once the direct body child `#root`
exists, it bounds `html`, `body` and that mount to the viewport with `overflow: clip`
and `overscroll-behavior: none`. This prevents document scrolling, including
programmatic scrolling and the outer elastic effect. Messages, sidebar lists,
editors and other nested scroll containers retain their own scrolling behavior.
The mount follows window resizing and WebView zoom through percentage dimensions.

The adapter uses the [Harness mount contract](https://github.com/deepseek-ai/deepseek-harness/blob/master/packages/client/web/src/base.css).
It writes individual style properties instead of adding an inline stylesheet,
so it also works when the server restricts stylesheets through CSP. The temporary
DOM observer disconnects when the mount appears. Each document navigation installs
the adapter again; pages without the Harness mount are left alone. It exposes no
native API, accesses no authorization data and does not add capabilities.
Once the body exists, the observer watches only direct body children and body
replacement, so nested mutations on other pages do not wake the adapter.

## Language preference

The persisted choice defaults to `system`, including migration of existing settings
files without a language field. At process startup, `sys-locale` reads the most
preferred OS locale (CoreFoundation on macOS; locale environment on Linux).
Windows reads the preferred UI language through the Windows locale API.
Only the primary language subtag is matched: `ru` selects Russian, `en` selects
English, and unsupported/missing values select English. A manual `en`/`ru` choice
overrides OS language; selecting System restores automatic choice on subsequent launches.

The same bundled JSON catalogs supply TypeScript UI text and Rust native menu/dialog
text. The frontend imports only their `ui` section through named JSON exports;
native menu/dialog strings are excluded from production JavaScript.
Rust returns stable serialized error categories instead of localized messages;
the frontend renders them in the current language and never reflects raw diagnostics.
Changing language atomically saves the choice, retitles existing native menu items in
place and sends a preferences event only to the two trusted local windows. The
connection's unsent address is retained during this event, and the remote browser
session is not reloaded. A download reads the current language when its dialog opens.

Linux also updates the displayed GTK submenu labels: Muda 0.20 wraps them in a
GtkBox, so its `set_text` changes the stored title without retitling that child.
The adapter walks only the native menu bar and submenus, preserving item identity,
accelerator groups and the server WebView.

The language selector stays enabled while saving: WebKitGTK can emit `change`
before its native popup closes, and disabling it can cancel the visual choice.
Frontend writes are queued in order. Native notifications translate the screen
without resetting a choice being made; Close/Escape waits for queued writes.

The new commands are in AppManifest and exact local-window capabilities. Remote
content receives no preference permission. macOS declares English/Russian bundle
localizations with localized network-access descriptions; OS-owned panel controls
follow the platform's language. Harness's own web language remains server-managed.

## Build footprint and persistence

Release builds use size-oriented optimization with thin LTO and retain panic
unwinding. Tauri prunes commands outside the static capabilities; dynamic ACL
mutation is disabled while compiled permissions still enforce the local/remote
boundary. The opener's injected click script is disabled: Rust navigation and
new-window callbacks already handle external HTTP(S) links.

Settings retain the last successfully loaded/saved value. Identical saves avoid
serialization and filesystem work; changed values still use a temporary sibling
and atomic replacement. Sanitized legacy settings differ from their loaded value
and are written on the next save. Failed writes remain retryable.

Build measurements and validation: [optimization.md](optimization.md).

## Local screen design

Palette: paper `#f6f8fc`, ink `#202936`, muted `#606c80`, DeepSeek blue
`#345bea`, input `#ffffff`, error `#b32940`. Dark palette follows system appearance.
System typography preserves macOS/Linux/Windows text rendering. A single left-aligned,
460px form sits in the window center; a compact bracket mark identifies the harness.
The input and connection state carry the visual emphasis. No marketing content,
animated decoration, permanent toolbar or additional dashboard is necessary here.
