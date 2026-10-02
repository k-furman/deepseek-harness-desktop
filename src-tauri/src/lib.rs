mod app;
mod browser;
mod connection;
mod endpoint;
mod error;
mod i18n;
mod menu;
mod preferences;
mod probe;
mod settings;
mod shell;
mod state;

use browser::{open_external, remote_profile};
use connection::{arm_timeout, verify_loaded};
use endpoint::{same_origin, Endpoint};
use error::AppError;
use state::{lock, Attempt, Desktop, Phase, Snapshot};
use std::time::{Duration, Instant};
use tauri::{
    webview::{NewWindowResponse, PageLoadEvent},
    AppHandle, Emitter, Manager, WebviewUrl, WebviewWindow, WebviewWindowBuilder,
};

const DEADLINE: Duration = Duration::from_secs(60);
const CONNECTION: &str = "connection";

fn require_local(window: &WebviewWindow) -> Result<(), AppError> {
    if window.label() == CONNECTION {
        Ok(())
    } else {
        Err(AppError::NotAllowed)
    }
}

#[tauri::command]
fn get_snapshot(window: WebviewWindow, app: AppHandle) -> Result<Snapshot, AppError> {
    require_local(&window)?;
    Ok(app.state::<Desktop>().snapshot())
}

#[tauri::command]
async fn connect(window: WebviewWindow, app: AppHandle, address: String) -> Result<(), AppError> {
    require_local(&window)?;
    let endpoint = Endpoint::parse(&address)?;
    let (sender, receiver) = tokio::sync::oneshot::channel();
    let native_app = app.clone();
    app.run_on_main_thread(move || {
        let _ = sender.send(start_connection(native_app, endpoint));
    })
    .map_err(|_| AppError::OpenConnection)?;
    receiver.await.map_err(|_| AppError::OpenConnection)?
}

fn start_connection(app: AppHandle, endpoint: Endpoint) -> Result<(), AppError> {
    stop_connection(&app, None);
    if let Some(window) = app.get_webview_window(CONNECTION) {
        remember_size(&app, &window);
    }
    let (id, dimensions) = {
        let desktop = app.state::<Desktop>();
        let mut session = lock(&desktop.session);
        session.serial += 1;
        let id = session.serial;
        session.attempt = Some(Attempt::new(id, endpoint.saved.clone()));
        session.phase = Phase::Connecting;
        session.error = None;
        let mut store = lock(&desktop.store);
        store.settings.last_url = endpoint.saved.to_string();
        (id, (store.settings.width, store.settings.height))
    };
    emit_snapshot(&app);
    arm_timeout(&app, id, 0);
    let save_app = app.clone();
    tauri::async_runtime::spawn_blocking(move || {
        let result = lock(&save_app.state::<Desktop>().store).save();
        if let Err(message) = result {
            fail_cycle(&save_app, id, 0, message);
        }
    });
    let navigation_app = app.clone();
    let new_window_app = app.clone();
    let page_app = app.clone();
    let origin = endpoint.saved.clone();
    let popup_origin = origin.clone();
    let builder = WebviewWindowBuilder::new(
        &app,
        format!("harness-{id}"),
        WebviewUrl::External(endpoint.launch),
    )
    .title("DeepSeek Harness Desktop")
    .inner_size(dimensions.0, dimensions.1)
    .min_inner_size(640.0, 480.0)
    .visible(false)
    .disable_drag_drop_handler()
    .enable_clipboard_access()
    .initialization_script(shell::initialization_script(&endpoint.saved))
    .on_navigation(move |url| {
        if same_origin(&origin, url) || (url.scheme() == "blob" && url.origin() == origin.origin())
        {
            return true;
        }
        open_external(&navigation_app, url);
        false
    })
    .on_new_window(move |url, _features| {
        if same_origin(&popup_origin, &url) {
            if let Some(window) = new_window_app.get_webview_window(&format!("harness-{id}")) {
                let _ = window.navigate(url);
            }
        } else {
            open_external(&new_window_app, &url);
        }
        NewWindowResponse::Deny
    })
    .on_page_load(move |window, payload| {
        let expected = {
            let desktop = page_app.state::<Desktop>();
            let session = lock(&desktop.session);
            session
                .attempt
                .as_ref()
                .filter(|a| a.id == id)
                .map(|a| a.url.clone())
        };
        if !expected.is_some_and(|expected| same_origin(&expected, payload.url())) {
            return;
        }
        match payload.event() {
            PageLoadEvent::Started => begin_reload(&page_app, id),
            PageLoadEvent::Finished => verify_loaded(&page_app, window, id),
        }
    });
    #[cfg(not(target_os = "linux"))]
    let builder = builder.on_download(browser::download);
    let builder = match remote_profile(builder, &app) {
        Ok(builder) => builder,
        Err(message) => {
            fail_cycle(&app, id, 0, message);
            return Err(message);
        }
    };
    match builder.build() {
        Ok(remote) => {
            if !lock(&app.state::<Desktop>().session)
                .attempt
                .as_ref()
                .is_some_and(|a| a.id == id)
            {
                browser::destroy_view(&remote);
                return Ok(());
            }
            #[cfg(target_os = "linux")]
            if browser::configure_remote_downloads(&remote).is_err() {
                fail_cycle(&app, id, 0, AppError::ConfigureDownloads);
                return Err(AppError::ConfigureDownloads);
            }
            let _ = remote.set_zoom(lock(&app.state::<Desktop>().session).zoom);
            if let Some(local) = app.get_webview_window(CONNECTION) {
                if let Ok(position) = local.outer_position() {
                    let _ = remote.set_position(position);
                }
            }
            Ok(())
        }
        Err(_) => {
            fail_cycle(&app, id, 0, AppError::OpenWindow);
            Err(AppError::OpenWindow)
        }
    }
}

#[tauri::command]
async fn cancel_connect(window: WebviewWindow, app: AppHandle) -> Result<(), AppError> {
    require_local(&window)?;
    let (sender, receiver) = tokio::sync::oneshot::channel();
    let native_app = app.clone();
    app.run_on_main_thread(move || {
        stop_connection(&native_app, None);
        let _ = sender.send(());
    })
    .map_err(|_| AppError::CancelConnection)?;
    receiver.await.map_err(|_| AppError::CancelConnection)
}

fn emit_snapshot(app: &AppHandle) {
    let _ = app.emit_to(
        CONNECTION,
        "connection-state",
        app.state::<Desktop>().snapshot(),
    );
}

fn active_window(app: &AppHandle) -> Option<WebviewWindow> {
    let label = {
        let desktop = app.state::<Desktop>();
        let session = lock(&desktop.session);
        if session.phase == Phase::Connected {
            session.attempt.as_ref().map(Attempt::label)
        } else {
            None
        }
    };
    app.get_webview_window(label.as_deref().unwrap_or(CONNECTION))
}

fn remember_size(app: &AppHandle, window: &WebviewWindow) {
    if let (Ok(size), Ok(scale)) = (window.inner_size(), window.scale_factor()) {
        let size = size.to_logical::<f64>(scale);
        let desktop = app.state::<Desktop>();
        let mut store = lock(&desktop.store);
        store.settings.width = size.width.clamp(640.0, 3840.0);
        store.settings.height = size.height.clamp(480.0, 2160.0);
    }
}

fn persist_settings(app: &AppHandle) {
    let app = app.clone();
    tauri::async_runtime::spawn_blocking(move || {
        let _ = lock(&app.state::<Desktop>().store).save();
    });
}

fn show_connection(app: &AppHandle) {
    if let Some(local) = app.get_webview_window(CONNECTION) {
        if let Some(remote) = active_window(app).filter(|w| w.label() != CONNECTION) {
            remember_size(app, &remote);
            if let Ok(size) = remote.inner_size() {
                let _ = local.set_size(size);
            }
            if let Ok(position) = remote.outer_position() {
                let _ = local.set_position(position);
            }
            let _ = remote.hide();
        }
        let _ = local.show();
        let _ = local.set_focus();
    }
}

fn stop_connection(app: &AppHandle, error: Option<AppError>) {
    show_connection(app);
    let label = {
        let desktop = app.state::<Desktop>();
        let mut session = lock(&desktop.session);
        session.phase = if error.is_some() {
            Phase::Error
        } else {
            Phase::Idle
        };
        session.error = error;
        session.attempt.take().map(|attempt| attempt.label())
    };
    if let Some(remote) = label.and_then(|label| app.get_webview_window(&label)) {
        browser::destroy_view(&remote);
    }
    persist_settings(app);
    emit_snapshot(app);
}

fn fail_cycle(app: &AppHandle, id: u64, cycle: u64, error: AppError) {
    let native_app = app.clone();
    let _ = app.run_on_main_thread(move || {
        let app = &native_app;
        let current = {
            let desktop = app.state::<Desktop>();
            let session = lock(&desktop.session);
            session.matches(id, cycle) && session.phase == Phase::Connecting
        };
        if current {
            stop_connection(app, Some(error));
        }
    });
}

fn begin_reload(app: &AppHandle, id: u64) {
    let cycle = {
        let desktop = app.state::<Desktop>();
        let mut session = lock(&desktop.session);
        if session.phase != Phase::Connected {
            return;
        }
        let Some(attempt) = session.attempt.as_mut().filter(|a| a.id == id) else {
            return;
        };
        attempt.cycle += 1;
        attempt.finish_work();
        attempt.started = Instant::now();
        attempt.verifying = false;
        let cycle = attempt.cycle;
        // Hide the remote before the phase changes, while active_window still finds it.
        drop(session);
        show_connection(app);
        lock(&desktop.session).phase = Phase::Connecting;
        cycle
    };
    emit_snapshot(app);
    arm_timeout(app, id, cycle);
}

fn reload_active(app: &AppHandle) {
    if let Some(window) = active_window(app) {
        let id = {
            let desktop = app.state::<Desktop>();
            let session = lock(&desktop.session);
            session.attempt.as_ref().map(|attempt| attempt.id)
        };
        if let Some(id) = id.filter(|_| window.label() != CONNECTION) {
            // Start before navigation: WKWebView can fail without a Started event.
            begin_reload(app, id);
        }
        let _ = window.reload();
    }
}

fn finish_download_navigation(app: &AppHandle, label: &str) {
    {
        let desktop = app.state::<Desktop>();
        let mut session = lock(&desktop.session);
        if session.phase != Phase::Connecting {
            return;
        }
        let Some(attempt) = session
            .attempt
            .as_mut()
            .filter(|attempt| attempt.label() == label && attempt.cycle > 0)
        else {
            return;
        };
        // A download cancels navigation while keeping the previously verified
        // page. Retire that navigation's timeout and return to the server view.
        attempt.cycle += 1;
        attempt.finish_work();
        session.phase = Phase::Connected;
        session.error = None;
    }
    if let Some(local) = app.get_webview_window(CONNECTION) {
        let _ = local.hide();
    }
    if let Some(remote) = app.get_webview_window(label) {
        let _ = remote.show();
        let _ = remote.set_focus();
    }
    emit_snapshot(app);
}

fn reset_session(app: &AppHandle) {
    let window = active_window(app).filter(|w| w.label() != CONNECTION);
    if let Some(window) = window {
        if window.clear_all_browsing_data().is_err() {
            stop_connection(app, Some(AppError::ResetSession));
            return;
        }
    } else {
        // A cancelled or failed attempt may still have written its persistent cookie.
        let builder = WebviewWindowBuilder::new(
            app,
            "session-reset",
            WebviewUrl::External(url::Url::parse("about:blank").expect("static URL")),
        )
        .visible(false);
        let result = remote_profile(builder, app)
            .and_then(|builder| builder.build().map_err(|_| AppError::ResetSession));
        match result {
            Ok(window) => {
                let result = window.clear_all_browsing_data();
                browser::destroy_view(&window);
                if result.is_err() {
                    stop_connection(app, Some(AppError::ResetSession));
                    return;
                }
            }
            Err(message) => {
                stop_connection(app, Some(message));
                return;
            }
        }
    }
    stop_connection(app, None);
}

pub use app::run;
