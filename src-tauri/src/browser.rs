use crate::error::AppError;
#[cfg(target_os = "linux")]
use crate::i18n::Language;
use crate::state::Desktop;
use std::path::PathBuf;
#[cfg(not(target_os = "linux"))]
use tauri::webview::DownloadEvent;
use tauri::Manager;
use tauri::{AppHandle, WebviewWindowBuilder};
use tauri_plugin_opener::OpenerExt;

pub fn remote_profile<'a>(
    builder: WebviewWindowBuilder<'a, tauri::Wry, AppHandle>,
    app: &AppHandle,
) -> Result<WebviewWindowBuilder<'a, tauri::Wry, AppHandle>, AppError> {
    #[cfg(target_os = "macos")]
    {
        let _ = app;
        // Stable UUID for this application's WKWebsiteDataStore (macOS 14+).
        Ok(builder.data_store_identifier([
            0x4d, 0x8c, 0x8f, 0xe9, 0x60, 0x39, 0x44, 0x0d, 0xb2, 0x5e, 0x78, 0x2d, 0x9a, 0x57,
            0x31, 0x42,
        ]))
    }
    #[cfg(not(target_os = "macos"))]
    {
        let directory = app
            .path()
            .app_data_dir()
            .map_err(|_| AppError::BrowserProfile)?
            .join("webview");
        std::fs::create_dir_all(&directory).map_err(|_| AppError::BrowserProfile)?;
        // GTK accelerator groups belong to a window. Sharing the same Muda tree
        // across replaceable windows unregisters another window's accelerators.
        #[cfg(target_os = "linux")]
        let builder =
            builder.menu(crate::menu::build_menu(app).map_err(|_| AppError::ConfigureMenu)?);
        Ok(builder.data_directory(directory))
    }
}

pub fn open_external(app: &AppHandle, url: &url::Url) {
    if matches!(url.scheme(), "http" | "https")
        && url.username().is_empty()
        && url.password().is_none()
    {
        let _ = app.opener().open_url(url.as_str(), None::<&str>);
    }
}

pub fn destroy_view(window: &tauri::WebviewWindow) {
    // Muda keys GTK menu bars by the native window address. Unregister before
    // GTK can reuse it, or a later connection may inherit an unattached menu.
    #[cfg(target_os = "linux")]
    let _ = window.remove_menu();
    let _ = window.destroy();
}

#[cfg(not(target_os = "linux"))]
pub fn download(webview: tauri::Webview, event: DownloadEvent<'_>) -> bool {
    match event {
        DownloadEvent::Requested { destination, .. } => {
            crate::finish_download_navigation(webview.app_handle(), webview.label());
            let filename = destination
                .file_name()
                .and_then(|name| name.to_str())
                .unwrap_or("download");
            match save_download(&webview, filename) {
                Some(path) => {
                    *destination = path;
                    true
                }
                None => false,
            }
        }
        DownloadEvent::Finished { success: false, .. } => {
            download_failed(&webview);
            true
        }
        _ => true,
    }
}

#[cfg(target_os = "linux")]
pub fn configure_remote_downloads(window: &tauri::WebviewWindow) -> tauri::Result<()> {
    use gtk::prelude::*;
    use webkit2gtk::{PolicyDecisionExt, ResponsePolicyDecisionExt, URIResponseExt, WebViewExt};
    // A window built hidden needs GTK menu descendants explicitly shown.
    window.show_menu()?;
    let app = window.app_handle().clone();
    let label = window.label().to_owned();
    window.with_webview(move |platform| {
        if let Some(context) = platform.inner().context() {
            replace_context_download_handler(&context, Some(app.clone()));
        }
        platform
            .inner()
            .connect_decide_policy(move |_, decision, kind| {
                if kind != webkit2gtk::PolicyDecisionType::Response {
                    return false;
                }
                let Some(response) = decision.downcast_ref::<webkit2gtk::ResponsePolicyDecision>()
                else {
                    return false;
                };
                let attachment = response
                    .response()
                    .and_then(|response| response.http_headers())
                    .and_then(|headers| headers.one("Content-Disposition"))
                    .is_some_and(|value| {
                        value
                            .split(';')
                            .next()
                            .unwrap_or("")
                            .trim()
                            .eq_ignore_ascii_case("attachment")
                    });
                if attachment
                    || (response.is_main_frame_main_resource()
                        && !response.is_mime_type_supported())
                {
                    crate::finish_download_navigation(&app, &label);
                    decision.download();
                    true
                } else {
                    false
                }
            });
    })
}

#[cfg(target_os = "linux")]
fn replace_context_download_handler(context: &webkit2gtk::WebContext, app: Option<AppHandle>) {
    use gtk::glib::{gobject_ffi, translate::IntoGlib};
    use gtk::prelude::*;
    // Wry installs a default handler for every view on the shared context. It
    // claims decide-destination before our Save dialog. Replace those handlers
    // on GTK's main thread; existing downloads retain their own callbacks.
    unsafe {
        let signal =
            gobject_ffi::g_signal_lookup(c"download-started".as_ptr(), context.type_().into_glib());
        // ID-only disconnect_matched requires GLib 2.78; Ubuntu 22.04 has 2.72.
        loop {
            let handler = gobject_ffi::g_signal_handler_find(
                context.as_ptr().cast(),
                gobject_ffi::G_SIGNAL_MATCH_ID,
                signal,
                0,
                std::ptr::null_mut(),
                std::ptr::null_mut(),
                std::ptr::null_mut(),
            );
            if handler == 0 {
                break;
            }
            gobject_ffi::g_signal_handler_disconnect(context.as_ptr().cast(), handler);
        }
    }
    gtk_download_handler(context, app);
}

#[cfg(target_os = "linux")]
fn gtk_download_handler(context: &webkit2gtk::WebContext, app: Option<AppHandle>) {
    use gtk::prelude::*;
    use webkit2gtk::{DownloadExt, WebContextExt};
    context.connect_download_started(move |_, download| {
        let dialog_app = app.clone();
        download.connect_decide_destination(move |download, filename| {
            let parent = download
                .web_view()
                .and_then(|view| view.toplevel())
                .and_then(|widget| widget.downcast::<gtk::ApplicationWindow>().ok());
            let name = std::path::Path::new(filename)
                .file_name()
                .and_then(|name| name.to_str())
                .unwrap_or("download");
            let language = dialog_app
                .as_ref()
                .map(|app| app.state::<Desktop>().language())
                .unwrap_or(Language::En);
            if let Some(path) = gtk_save_dialog(parent.as_ref(), name, language) {
                if let Ok(uri) = url::Url::from_file_path(path) {
                    download.set_allow_overwrite(true);
                    download.set_destination(uri.as_str());
                    return true;
                }
            }
            download.cancel();
            true
        });
        // Track the native error per download. User cancellation is normal;
        // it must not mark this or subsequent downloads as failures.
        let error_app = app.clone();
        download.connect_failed(move |download, error| {
            if !error.matches(webkit2gtk::DownloadError::CancelledByUser) {
                let parent = download
                    .web_view()
                    .and_then(|view| view.toplevel())
                    .and_then(|widget| widget.downcast::<gtk::ApplicationWindow>().ok());
                let language = error_app
                    .as_ref()
                    .map(|app| app.state::<Desktop>().language())
                    .unwrap_or(Language::En);
                gtk_download_failed(parent.as_ref(), language);
            }
        });
    });
}

#[cfg(target_os = "linux")]
fn gtk_save_dialog(
    parent: Option<&gtk::ApplicationWindow>,
    filename: &str,
    language: Language,
) -> Option<PathBuf> {
    use gtk::prelude::*;
    // Download callbacks already run on GTK's main thread. Use its nested modal
    // loop instead of a blocking bridge to a second GTK thread.
    let dialog = gtk::FileChooserDialog::with_buttons(
        Some(language.native("saveFile")),
        parent,
        gtk::FileChooserAction::Save,
        &[
            (language.native("cancel"), gtk::ResponseType::Cancel),
            (language.native("save"), gtk::ResponseType::Accept),
        ],
    );
    dialog.set_modal(true);
    dialog.set_current_name(filename);
    dialog.set_do_overwrite_confirmation(true);
    dialog.set_default_response(gtk::ResponseType::Accept);
    let path = (dialog.run() == gtk::ResponseType::Accept)
        .then(|| dialog.filename())
        .flatten();
    dialog.close();
    path
}

#[cfg(not(target_os = "linux"))]
fn save_download(webview: &tauri::Webview, filename: &str) -> Option<PathBuf> {
    let language = webview.app_handle().state::<Desktop>().language();
    rfd::FileDialog::new()
        .set_title(language.native("saveFile"))
        .set_file_name(filename)
        .save_file()
}

#[cfg(target_os = "linux")]
fn gtk_download_failed(parent: Option<&gtk::ApplicationWindow>, language: Language) {
    use gtk::prelude::*;
    let dialog = gtk::MessageDialog::new(
        parent,
        gtk::DialogFlags::MODAL,
        gtk::MessageType::Error,
        gtk::ButtonsType::Ok,
        language.native("downloadFailed"),
    );
    dialog.set_title(language.native("download"));
    dialog.run();
    dialog.close();
}

#[cfg(not(target_os = "linux"))]
fn download_failed(webview: &tauri::Webview) {
    let language = webview.app_handle().state::<Desktop>().language();
    rfd::MessageDialog::new()
        .set_title(language.native("download"))
        .set_description(language.native("downloadFailed"))
        .set_level(rfd::MessageLevel::Error)
        .show();
}

#[cfg(all(test, target_os = "linux"))]
mod tests {
    use super::*;
    use gtk::prelude::*;

    #[test]
    #[ignore = "Requires an isolated Linux display (run under Xvfb)"]
    fn save_dialog_cancels_inside_the_gtk_event_loop() {
        use std::io::{Read, Write};
        use webkit2gtk::{DownloadExt, WebContextExt};

        gtk::init().expect("GTK display");
        let event_loop = gtk::glib::MainLoop::new(None, false);
        let completed = std::rc::Rc::new(std::cell::Cell::new(false));
        let result = completed.clone();
        let finish = event_loop.clone();
        gtk::glib::idle_add_local_once(move || {
            gtk::glib::timeout_add_local_once(std::time::Duration::from_millis(200), || {
                for window in gtk::Window::list_toplevels() {
                    if let Ok(dialog) = window.downcast::<gtk::FileChooserDialog>() {
                        dialog.response(gtk::ResponseType::Cancel);
                    }
                }
            });
            result.set(gtk_save_dialog(None, "fixture.txt", Language::En).is_none());
            finish.quit();
        });
        event_loop.run();
        assert!(completed.get());

        // Exercise real native downloads on the shared context: cancel one,
        // then save another. This catches retained failure state and modal-loop
        // deadlocks, and checks the downloaded content rather than only signals.
        let listener = std::net::TcpListener::bind("127.0.0.1:0").unwrap();
        let address = format!("http://{}/fixture.txt", listener.local_addr().unwrap());
        let server = std::thread::spawn(move || {
            for mut stream in listener.incoming().take(2).flatten() {
                let mut request = [0; 8192];
                let _ = stream.read(&mut request);
                let _ = stream.write_all(b"HTTP/1.1 200 OK\r\nContent-Length: 8\r\nContent-Disposition: attachment; filename=fixture.txt\r\nConnection: close\r\n\r\nfixture\n");
            }
        });
        let directory = tempfile::tempdir().unwrap();
        let path = directory.path().join("fixture.txt");
        let context = webkit2gtk::WebContext::new();
        // Reproduce Wry's earlier handler claiming the destination. Replacement
        // must work on the minimum distro's GLib and allow our dialog to run.
        context.connect_download_started(|_, download| {
            download.connect_decide_destination(|_, _| true);
        });
        replace_context_download_handler(&context, None);
        let dialogs = std::rc::Rc::new(std::cell::Cell::new(0));
        let responded = dialogs.clone();
        let destination = path.clone();
        let timer =
            gtk::glib::timeout_add_local(std::time::Duration::from_millis(100), move || {
                for window in gtk::Window::list_toplevels() {
                    if let Ok(dialog) = window.downcast::<gtk::FileChooserDialog>() {
                        match responded.get() {
                            0 => dialog.response(gtk::ResponseType::Cancel),
                            1 => {
                                dialog.set_filename(&destination);
                                dialog.response(gtk::ResponseType::Accept);
                            }
                            _ => continue,
                        }
                        responded.set(responded.get() + 1);
                    }
                }
                gtk::glib::ControlFlow::Continue
            });
        let finished = std::rc::Rc::new(std::cell::Cell::new(0));
        let count = finished.clone();
        let downloads_done = event_loop.clone();
        let next_context = context.clone();
        let next_address = address.clone();
        context.connect_download_started(move |_, download| {
            let count = count.clone();
            let finish = downloads_done.clone();
            let context = next_context.clone();
            let address = next_address.clone();
            download.connect_finished(move |_| {
                count.set(count.get() + 1);
                if count.get() == 1 {
                    let context = context.clone();
                    let address = address.clone();
                    gtk::glib::idle_add_local_once(move || {
                        context.download_uri(&address);
                    });
                } else {
                    finish.quit();
                }
            });
        });
        context.download_uri(&address);
        event_loop.run();
        timer.remove();
        server.join().unwrap();
        assert_eq!(finished.get(), 2);
        assert_eq!(dialogs.get(), 2);
        assert_eq!(std::fs::read(path).unwrap(), b"fixture\n");
    }
}
