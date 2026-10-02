use crate::i18n::Language;
use crate::state::{lock, Desktop};
use crate::{active_window, reload_active, remember_size, reset_session, stop_connection};
use tauri::{
    menu::{Menu, MenuItem, MenuItemKind, PredefinedMenuItem, Submenu},
    AppHandle, Manager,
};

pub fn build_menu(app: &AppHandle) -> tauri::Result<Menu<tauri::Wry>> {
    let language = app.state::<Desktop>().language();
    let preferences = MenuItem::with_id(
        app,
        "preferences",
        language.menu("preferences"),
        true,
        Some("CmdOrCtrl+,"),
    )?;
    let switch = MenuItem::with_id(
        app,
        "connect-server",
        language.menu("switch"),
        true,
        Some("CmdOrCtrl+L"),
    )?;
    let reload = MenuItem::with_id(
        app,
        "reload",
        language.menu("reload"),
        true,
        Some("CmdOrCtrl+R"),
    )?;
    let reset = MenuItem::with_id(
        app,
        "reset-session",
        language.menu("reset"),
        true,
        None::<&str>,
    )?;
    let zoom_in = MenuItem::with_id(
        app,
        "zoom-in",
        language.menu("zoomIn"),
        true,
        Some("CmdOrCtrl+="),
    )?;
    let zoom_out = MenuItem::with_id(
        app,
        "zoom-out",
        language.menu("zoomOut"),
        true,
        Some("CmdOrCtrl+-"),
    )?;
    let zoom_reset = MenuItem::with_id(
        app,
        "zoom-reset",
        language.menu("zoomReset"),
        true,
        Some("CmdOrCtrl+0"),
    )?;
    let show = MenuItem::with_id(
        app,
        "show-window",
        language.menu("show"),
        true,
        None::<&str>,
    )?;
    let quit = MenuItem::with_id(
        app,
        "quit",
        language.menu("quit"),
        true,
        Some("CmdOrCtrl+Q"),
    )?;
    #[cfg(target_os = "macos")]
    let application = Submenu::with_items(
        app,
        "DeepSeek Harness Desktop",
        true,
        &[
            &PredefinedMenuItem::about(app, Some(language.menu("about")), None)?,
            &PredefinedMenuItem::separator(app)?,
            &preferences,
            &PredefinedMenuItem::separator(app)?,
            &PredefinedMenuItem::hide(app, Some(language.menu("hide")))?,
            &PredefinedMenuItem::hide_others(app, Some(language.menu("hideOthers")))?,
            &PredefinedMenuItem::show_all(app, Some(language.menu("showAll")))?,
            &PredefinedMenuItem::separator(app)?,
            &quit,
        ],
    )?;
    #[cfg(not(target_os = "macos"))]
    let application = Submenu::with_items(
        app,
        language.menu("application"),
        true,
        &[
            &PredefinedMenuItem::about(app, Some(language.menu("about")), None)?,
            &preferences,
            &quit,
        ],
    )?;
    let file = Submenu::with_items(app, language.menu("file"), true, &[&switch, &reset])?;
    let edit = Submenu::with_items(
        app,
        language.menu("edit"),
        true,
        &[
            &PredefinedMenuItem::undo(app, Some(language.menu("undo")))?,
            &PredefinedMenuItem::redo(app, Some(language.menu("redo")))?,
            &PredefinedMenuItem::separator(app)?,
            &PredefinedMenuItem::cut(app, Some(language.menu("cut")))?,
            &PredefinedMenuItem::copy(app, Some(language.menu("copy")))?,
            &PredefinedMenuItem::paste(app, Some(language.menu("paste")))?,
            &PredefinedMenuItem::select_all(app, Some(language.menu("selectAll")))?,
        ],
    )?;
    #[cfg(target_os = "windows")]
    let fullscreen = MenuItem::with_id(
        app,
        "toggle-fullscreen",
        language.menu("fullscreen"),
        true,
        Some("F11"),
    )?;
    #[cfg(not(target_os = "windows"))]
    let fullscreen = PredefinedMenuItem::fullscreen(app, Some(language.menu("fullscreen")))?;
    let view = Submenu::with_items(
        app,
        language.menu("view"),
        true,
        &[
            &reload,
            &PredefinedMenuItem::separator(app)?,
            &zoom_in,
            &zoom_out,
            &zoom_reset,
            &fullscreen,
        ],
    )?;
    let windows = Submenu::with_items(
        app,
        language.menu("window"),
        true,
        &[
            &PredefinedMenuItem::minimize(app, Some(language.menu("minimize")))?,
            &show,
            &PredefinedMenuItem::close_window(app, Some(language.menu("closeWindow")))?,
        ],
    )?;
    Menu::with_items(app, &[&application, &file, &edit, &view, &windows])
}

pub fn setup_menu(app: &AppHandle) -> tauri::Result<()> {
    app.set_menu(build_menu(app)?)?;
    app.on_menu_event(|app, event| match event.id().as_ref() {
        "connect-server" => stop_connection(app, None),
        "preferences" => {
            let _ = crate::preferences::show(app);
        }
        "reload" => reload_active(app),
        #[cfg(target_os = "windows")]
        "toggle-fullscreen" => {
            if let Some(window) = active_window(app) {
                if let Ok(fullscreen) = window.is_fullscreen() {
                    let _ = window.set_fullscreen(!fullscreen);
                }
            }
        }
        "reset-session" => reset_session(app),
        "show-window" => {
            if let Some(window) = active_window(app) {
                let _ = window.show();
                let _ = window.set_focus();
            }
        }
        "zoom-in" | "zoom-out" | "zoom-reset" => {
            let desktop = app.state::<Desktop>();
            let zoom = {
                let mut session = lock(&desktop.session);
                session.zoom = match event.id().as_ref() {
                    "zoom-in" => (session.zoom + 0.1).min(2.0),
                    "zoom-out" => (session.zoom - 0.1).max(0.5),
                    _ => 1.0,
                };
                session.zoom
            };
            for window in app.webview_windows().values() {
                let _ = window.set_zoom(zoom);
            }
        }
        "quit" => {
            if let Some(window) = active_window(app) {
                remember_size(app, &window);
            }
            let _ = lock(&app.state::<Desktop>().store).save();
            app.exit(0);
        }
        _ => {}
    });
    Ok(())
}

// Retitle existing native items in place: GTK accelerator groups keep their owners.
pub fn localize(app: &AppHandle, language: Language) -> tauri::Result<()> {
    if let Some(menu) = app.menu() {
        localize_items(menu.items()?, language)?;
    }
    for window in app.webview_windows().values() {
        if let Some(menu) = window.menu() {
            localize_items(menu.items()?, language)?;
        }
        #[cfg(target_os = "linux")]
        {
            use gtk::prelude::*;
            for child in window.default_vbox()?.children() {
                if child.is::<gtk::MenuBar>() {
                    localize_gtk_labels(&child, language);
                }
            }
        }
    }
    Ok(())
}

#[cfg(target_os = "linux")]
fn localize_gtk_labels(widget: &gtk::Widget, language: Language) {
    use gtk::prelude::*;
    // Muda 0.20 places submenu labels inside a GtkBox. GtkMenuItem::set_label
    // cannot retitle that child, so update the displayed label in place too.
    if let Some(label) = widget.downcast_ref::<gtk::Label>() {
        if let Some(text) = language.translated_menu_text(label.text().as_str()) {
            label.set_text_with_mnemonic(text);
        }
    }
    if let Some(item) = widget.downcast_ref::<gtk::MenuItem>() {
        if let Some(submenu) = item.submenu() {
            localize_gtk_labels(&submenu, language);
        }
    }
    if let Some(container) = widget.downcast_ref::<gtk::Container>() {
        for child in container.children() {
            localize_gtk_labels(&child, language);
        }
    }
}

fn localize_items(items: Vec<MenuItemKind<tauri::Wry>>, language: Language) -> tauri::Result<()> {
    for item in items {
        match item {
            MenuItemKind::MenuItem(item) => {
                if let Some(text) = language.translated_menu_text(&item.text()?) {
                    item.set_text(text)?;
                }
            }
            MenuItemKind::Predefined(item) => {
                if let Some(text) = language.translated_menu_text(&item.text()?) {
                    item.set_text(text)?;
                }
            }
            MenuItemKind::Submenu(item) => {
                if let Some(text) = language.translated_menu_text(&item.text()?) {
                    item.set_text(text)?;
                }
                localize_items(item.items()?, language)?;
            }
            _ => {}
        }
    }
    Ok(())
}
