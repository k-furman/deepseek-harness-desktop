use crate::{
    browser,
    error::AppError,
    i18n::{Language, LanguageSetting},
    menu,
    state::{lock, Desktop},
    CONNECTION,
};
use serde::Serialize;
use tauri::{
    webview::NewWindowResponse, AppHandle, Emitter, Manager, WebviewUrl, WebviewWindow,
    WebviewWindowBuilder,
};

pub const WINDOW: &str = "preferences";

#[derive(Clone, Copy, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct Preferences {
    pub language: LanguageSetting,
    pub effective_language: Language,
    pub system_language: Language,
}

fn snapshot(app: &AppHandle) -> Preferences {
    let desktop = app.state::<Desktop>();
    let language = lock(&desktop.store).settings.language;
    Preferences {
        language,
        effective_language: language.resolve(desktop.system_language),
        system_language: desktop.system_language,
    }
}

fn require_preferences(window: &WebviewWindow) -> Result<(), AppError> {
    if window.label() == WINDOW {
        Ok(())
    } else {
        Err(AppError::NotAllowed)
    }
}

pub fn show(app: &AppHandle) -> Result<(), AppError> {
    if let Some(window) = app.get_webview_window(WINDOW) {
        window.show().map_err(|_| AppError::OpenSettings)?;
        return window.set_focus().map_err(|_| AppError::OpenSettings);
    }
    let language = app.state::<Desktop>().language();
    let local_app = app.clone();
    let builder = WebviewWindowBuilder::new(app, WINDOW, WebviewUrl::App("settings.html".into()))
        .title(language.menu("preferences").trim_end_matches('…'))
        .inner_size(500.0, 380.0)
        .resizable(false)
        .maximizable(false)
        .minimizable(false)
        .center()
        .on_navigation(move |url| crate::app::local_navigation(&local_app, url))
        .on_new_window(|_, _| NewWindowResponse::Deny);
    #[cfg(target_os = "linux")]
    let builder = {
        let directory = app
            .path()
            .app_data_dir()
            .map_err(|_| AppError::OpenSettings)?
            .join("webview");
        builder
            .data_directory(directory)
            .menu(menu::build_menu(app).map_err(|_| AppError::ConfigureMenu)?)
    };
    builder.build().map_err(|_| AppError::OpenSettings)?;
    Ok(())
}

#[tauri::command]
pub async fn open_preferences(window: WebviewWindow, app: AppHandle) -> Result<(), AppError> {
    if window.label() != CONNECTION {
        return Err(AppError::NotAllowed);
    }
    let (sender, receiver) = tokio::sync::oneshot::channel();
    let native_app = app.clone();
    app.run_on_main_thread(move || {
        let _ = sender.send(show(&native_app));
    })
    .map_err(|_| AppError::OpenSettings)?;
    receiver.await.map_err(|_| AppError::OpenSettings)?
}

#[tauri::command]
pub fn get_preferences(window: WebviewWindow, app: AppHandle) -> Result<Preferences, AppError> {
    require_preferences(&window)?;
    Ok(snapshot(&app))
}

#[tauri::command]
pub async fn set_language(
    window: WebviewWindow,
    app: AppHandle,
    language: LanguageSetting,
) -> Result<Preferences, AppError> {
    require_preferences(&window)?;
    let save_app = app.clone();
    tauri::async_runtime::spawn_blocking(move || {
        let desktop = save_app.state::<Desktop>();
        let mut store = lock(&desktop.store);
        let previous = store.settings.language;
        store.settings.language = language;
        if let Err(error) = store.save() {
            store.settings.language = previous;
            return Err(error);
        }
        Ok(())
    })
    .await
    .map_err(|_| AppError::SaveSettings)??;
    let (sender, receiver) = tokio::sync::oneshot::channel();
    let native_app = app.clone();
    app.run_on_main_thread(move || {
        let current = snapshot(&native_app);
        let result = menu::localize(&native_app, current.effective_language)
            .map_err(|_| AppError::ConfigureMenu);
        if let Some(window) = native_app.get_webview_window(WINDOW) {
            let _ = window.set_title(
                current
                    .effective_language
                    .menu("preferences")
                    .trim_end_matches('…'),
            );
        }
        for label in [CONNECTION, WINDOW] {
            let _ = native_app.emit_to(label, "preferences-changed", current);
        }
        let _ = sender.send(result.map(|_| current));
    })
    .map_err(|_| AppError::SaveSettings)?;
    receiver.await.map_err(|_| AppError::SaveSettings)?
}

#[tauri::command]
pub fn close_preferences(window: WebviewWindow) -> Result<(), AppError> {
    require_preferences(&window)?;
    browser::destroy_view(&window);
    Ok(())
}
