use crate::endpoint::{bundled_origin, same_origin};
use crate::state::{lock, Desktop, Session};
use crate::{active_window, menu, preferences, remember_size, settings, CONNECTION};
use std::path::PathBuf;
use tauri::{webview::NewWindowResponse, AppHandle, Manager, WebviewUrl, WebviewWindowBuilder};

pub fn local_navigation(app: &AppHandle, url: &url::Url) -> bool {
    bundled_origin(url, cfg!(target_os = "windows"))
        || (cfg!(debug_assertions)
            && app
                .config()
                .build
                .dev_url
                .as_ref()
                .is_some_and(|origin| same_origin(origin, url)))
}

pub fn run() {
    let application = tauri::Builder::default()
        .plugin(tauri_plugin_single_instance::init(|app, _args, _cwd| {
            if let Some(window) = active_window(app) {
                let _ = window.show();
                let _ = window.set_focus();
            }
        }))
        // Native navigation callbacks already open external links. The plugin's
        // injected click handler invokes IPC unavailable to the remote WebView.
        .plugin(
            tauri_plugin_opener::Builder::new()
                .open_js_links_on_click(false)
                .build(),
        )
        .invoke_handler(tauri::generate_handler![
            crate::get_snapshot,
            crate::connect,
            crate::cancel_connect,
            preferences::open_preferences,
            preferences::get_preferences,
            preferences::set_language,
            preferences::close_preferences
        ])
        .setup(|app| {
            let path: PathBuf = app.path().app_config_dir()?.join("settings.json");
            app.manage(Desktop {
                session: std::sync::Mutex::new(Session::default()),
                store: std::sync::Mutex::new(settings::Store::load(path)),
                system_language: crate::i18n::Language::system(),
                probe: crate::probe::Probe::default(),
            });
            menu::setup_menu(app.handle())?;
            let dimensions = {
                let desktop = app.state::<Desktop>();
                let store = lock(&desktop.store);
                (store.settings.width, store.settings.height)
            };
            let local_app = app.handle().clone();
            let local =
                WebviewWindowBuilder::new(app, CONNECTION, WebviewUrl::App("index.html".into()))
                    .title("DeepSeek Harness Desktop")
                    .inner_size(dimensions.0, dimensions.1)
                    .min_inner_size(640.0, 480.0)
                    .center()
                    .on_navigation(move |url| local_navigation(&local_app, url))
                    .on_new_window(|_, _| NewWindowResponse::Deny);
            #[cfg(target_os = "linux")]
            let local = {
                let directory = app.path().app_data_dir()?.join("webview");
                std::fs::create_dir_all(&directory)?;
                local.data_directory(directory)
            };
            local.build()?;
            Ok(())
        })
        .on_window_event(|window, event| {
            if let tauri::WindowEvent::CloseRequested { api, .. } = event {
                api.prevent_close();
                let app = window.app_handle();
                if window.label() == preferences::WINDOW {
                    if let Some(view) = app.get_webview_window(preferences::WINDOW) {
                        crate::browser::destroy_view(&view);
                    }
                    return;
                }
                if let Some(active) = active_window(app) {
                    remember_size(app, &active);
                }
                let _ = lock(&app.state::<Desktop>().store).save();
                #[cfg(target_os = "macos")]
                for (_, window) in app.webview_windows() {
                    let _ = window.hide();
                }
                #[cfg(not(target_os = "macos"))]
                app.exit(0);
            }
        })
        .build(tauri::generate_context!())
        .expect("failed to initialize DeepSeek Harness Desktop");
    application.run(|app, event| {
        #[cfg(target_os = "macos")]
        if let tauri::RunEvent::Reopen { .. } = event {
            if let Some(window) = active_window(app) {
                let _ = window.show();
                let _ = window.set_focus();
            }
        }
        #[cfg(not(target_os = "macos"))]
        let _ = (app, event);
    });
}
