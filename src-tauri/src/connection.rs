// Native connection workers are scoped to an attempt and its reload cycle.
use crate::{
    emit_snapshot,
    error::AppError,
    fail_cycle, probe, remember_size,
    state::{lock, Desktop, Phase},
    CONNECTION, DEADLINE,
};
use tauri::{AppHandle, Manager, WebviewWindow};

pub fn arm_timeout(app: &AppHandle, id: u64, cycle: u64) {
    let (url, remaining, mut cancellation) = {
        let desktop = app.state::<Desktop>();
        let mut session = lock(&desktop.session);
        if !session.matches(id, cycle) || session.phase != Phase::Connecting {
            return;
        }
        let attempt = session.attempt.as_mut().expect("matched attempt");
        (
            attempt.url.clone(),
            DEADLINE.saturating_sub(attempt.started.elapsed()),
            attempt.start_work(),
        )
    };
    let app = app.clone();
    let probe = app.state::<Desktop>().probe.clone();
    tauri::async_runtime::spawn(async move {
        let deadline = tokio::time::Instant::now() + remaining;
        tokio::select! {
            biased;
            _ = cancellation.changed() => {},
            error = async {
                if let Err(error) = probe.check_transport(url, remaining).await {
                    return error;
                }
                tokio::time::sleep_until(deadline).await;
                probe::TIMEOUT_ERROR
            } => fail_cycle(&app, id, cycle, error),
        }
    });
}

pub fn verify_loaded(app: &AppHandle, window: WebviewWindow, id: u64) {
    let (url, cycle, remaining, mut cancellation) = {
        let desktop = app.state::<Desktop>();
        let mut session = lock(&desktop.session);
        if session.phase != Phase::Connecting {
            return;
        }
        let Some(attempt) = session
            .attempt
            .as_mut()
            .filter(|a| a.id == id && !a.verifying)
        else {
            return;
        };
        let Some(cancellation) = attempt.cancellation() else {
            return;
        };
        attempt.verifying = true;
        (
            attempt.url.clone(),
            attempt.cycle,
            DEADLINE.saturating_sub(attempt.started.elapsed()),
            cancellation,
        )
    };
    let app = app.clone();
    let probe = app.state::<Desktop>().probe.clone();
    tauri::async_runtime::spawn(async move {
        let verification = probe.verify(url, remaining, |cookie_url| {
            let cookie_window = window.clone();
            async move {
                tauri::async_runtime::spawn_blocking(move || {
                    // WKWebView's Wry URL filter compares domains, which excludes IP
                    // literals. Read the store and let Probe apply the exact filter.
                    if cfg!(target_os = "macos") && cookie_url.domain().is_none() {
                        cookie_window.cookies()
                    } else {
                        cookie_window.cookies_for_url(cookie_url)
                    }
                })
                .await
                .map_err(|_| AppError::BrowserSession)?
                .map_err(|_| AppError::BrowserSession)
            }
        });
        let result = tokio::select! {
            biased;
            _ = cancellation.changed() => return,
            result = verification => result,
        };
        match result {
            Ok(()) => {
                let native_app = app.clone();
                let _ = app.run_on_main_thread(move || {
                    let app = native_app;
                    let current = {
                        let desktop = app.state::<Desktop>();
                        let mut session = lock(&desktop.session);
                        if session.matches(id, cycle) && session.phase == Phase::Connecting {
                            session
                                .attempt
                                .as_mut()
                                .expect("matched attempt")
                                .finish_work();
                            session.phase = Phase::Connected;
                            session.error = None;
                            true
                        } else {
                            false
                        }
                    };
                    if current {
                        if let Some(local) = app.get_webview_window(CONNECTION) {
                            remember_size(&app, &local);
                            if let Ok(size) = local.inner_size() {
                                let _ = window.set_size(size);
                            }
                            let _ = local.hide();
                        }
                        let _ = window.show();
                        let _ = window.set_focus();
                        emit_snapshot(&app);
                    }
                });
            }
            Err(message) => fail_cycle(&app, id, cycle, message),
        }
    });
}
