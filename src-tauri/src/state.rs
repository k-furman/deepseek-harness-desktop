use crate::settings::Store;
use crate::{error::AppError, i18n::Language, probe::Probe};
use serde::Serialize;
use std::{
    sync::{Mutex, MutexGuard},
    time::Instant,
};
use tokio::sync::watch;
use url::Url;

pub fn lock<T>(mutex: &Mutex<T>) -> MutexGuard<'_, T> {
    mutex
        .lock()
        .unwrap_or_else(|poisoned| poisoned.into_inner())
}

#[derive(Clone, Copy, PartialEq, Serialize)]
#[serde(rename_all = "camelCase")]
pub enum Phase {
    Idle,
    Connecting,
    Connected,
    Error,
}

#[derive(Clone, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct Snapshot {
    pub phase: Phase,
    pub last_url: String,
    pub error: Option<AppError>,
    pub language: Language,
}

pub struct Attempt {
    pub id: u64,
    pub cycle: u64,
    pub url: Url,
    pub started: Instant,
    pub verifying: bool,
    work: Option<watch::Sender<()>>,
}

impl Attempt {
    pub fn new(id: u64, url: Url) -> Self {
        Self {
            id,
            cycle: 0,
            url,
            started: Instant::now(),
            verifying: false,
            work: None,
        }
    }

    pub fn label(&self) -> String {
        format!("harness-{}", self.id)
    }

    pub fn start_work(&mut self) -> watch::Receiver<()> {
        let (sender, receiver) = watch::channel(());
        // Dropping the previous sender also cancels a superseded cycle.
        self.work = Some(sender);
        receiver
    }

    pub fn cancellation(&self) -> Option<watch::Receiver<()>> {
        self.work.as_ref().map(watch::Sender::subscribe)
    }

    pub fn finish_work(&mut self) {
        // Every receiver wakes when the sole sender is dropped. Dropping the
        // attempt on Cancel/replacement has the same effect, even before polling.
        self.work = None;
    }
}

pub struct Session {
    pub serial: u64,
    pub attempt: Option<Attempt>,
    pub phase: Phase,
    pub error: Option<AppError>,
    pub zoom: f64,
}

impl Default for Session {
    fn default() -> Self {
        Self {
            serial: 0,
            attempt: None,
            phase: Phase::Idle,
            error: None,
            zoom: 1.0,
        }
    }
}

impl Session {
    pub fn matches(&self, id: u64, cycle: u64) -> bool {
        self.attempt
            .as_ref()
            .is_some_and(|a| a.id == id && a.cycle == cycle)
    }
}

pub struct Desktop {
    pub session: Mutex<Session>,
    pub store: Mutex<Store>,
    pub system_language: Language,
    pub probe: Probe,
}

impl Desktop {
    pub fn language(&self) -> Language {
        lock(&self.store)
            .settings
            .language
            .resolve(self.system_language)
    }

    pub fn snapshot(&self) -> Snapshot {
        let session = lock(&self.session);
        let store = lock(&self.store);
        Snapshot {
            phase: session.phase,
            last_url: store.settings.last_url.clone(),
            error: session.error,
            language: store.settings.language.resolve(self.system_language),
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn cancelled_and_replaced_attempts_cannot_finish_new_connections() {
        let mut session = Session {
            attempt: Some(Attempt::new(
                2,
                Url::parse("http://localhost:3000/").unwrap(),
            )),
            ..Session::default()
        };
        session.attempt.as_mut().unwrap().cycle = 3;
        assert!(!session.matches(1, 3));
        assert!(!session.matches(2, 2));
        assert!(session.matches(2, 3));
        session.attempt = None;
        assert!(!session.matches(2, 3));
    }

    #[tokio::test]
    async fn completion_replacement_and_drop_cancel_all_cycle_workers() {
        let mut attempt = Attempt::new(1, Url::parse("http://localhost:3000/").unwrap());
        let mut transport = attempt.start_work();
        let mut verification = attempt.cancellation().unwrap();
        assert!(transport.has_changed().is_ok());
        attempt.finish_work();
        assert!(transport.changed().await.is_err());
        assert!(verification.changed().await.is_err());
        assert!(attempt.cancellation().is_none());

        let mut old = attempt.start_work();
        let mut current = attempt.start_work();
        assert!(old.changed().await.is_err());
        assert!(current.has_changed().is_ok());
        drop(attempt);
        assert!(current.changed().await.is_err());
    }
}
