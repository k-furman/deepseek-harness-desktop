use crate::endpoint::Endpoint;
use crate::error::AppError;
use crate::i18n::LanguageSetting;
use serde::{Deserialize, Serialize};
use std::{fs, path::PathBuf};

#[derive(Clone, PartialEq, Deserialize, Serialize)]
#[serde(default, rename_all = "camelCase")]
pub struct Settings {
    pub last_url: String,
    pub width: f64,
    pub height: f64,
    pub language: LanguageSetting,
}

impl Default for Settings {
    fn default() -> Self {
        Self {
            last_url: String::new(),
            width: 1080.0,
            height: 780.0,
            language: LanguageSetting::System,
        }
    }
}

pub struct Store {
    pub path: PathBuf,
    pub settings: Settings,
    saved: Option<Settings>,
}

impl Store {
    pub fn load(path: PathBuf) -> Self {
        let settings = fs::metadata(&path)
            .ok()
            .filter(|m| m.len() <= 16_384)
            .and_then(|_| fs::read(&path).ok())
            .and_then(|bytes| serde_json::from_slice::<Settings>(&bytes).ok());
        let mut store = Self {
            path,
            settings: settings.clone().unwrap_or_default(),
            saved: settings,
        };
        store.settings.last_url = Endpoint::parse(&store.settings.last_url)
            .map(|endpoint| endpoint.saved.to_string())
            .unwrap_or_default();
        store.settings.width = if store.settings.width.is_finite() {
            store.settings.width.clamp(640.0, 3840.0)
        } else {
            1080.0
        };
        store.settings.height = if store.settings.height.is_finite() {
            store.settings.height.clamp(480.0, 2160.0)
        } else {
            780.0
        };
        store
    }

    pub fn save(&mut self) -> Result<(), AppError> {
        if self.saved.as_ref() == Some(&self.settings) {
            return Ok(());
        }
        let parent = self.path.parent().ok_or(AppError::SaveSettings)?;
        fs::create_dir_all(parent).map_err(|_| AppError::SaveSettings)?;
        let bytes =
            serde_json::to_vec_pretty(&self.settings).map_err(|_| AppError::SaveSettings)?;
        let temporary = self.path.with_extension("json.tmp");
        fs::write(&temporary, bytes).map_err(|_| AppError::SaveSettings)?;
        fs::rename(temporary, &self.path).map_err(|_| AppError::SaveSettings)?;
        self.saved = Some(self.settings.clone());
        Ok(())
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn settings_round_trip_and_token_scrubbing() {
        let directory = tempfile::tempdir().unwrap();
        let path = directory.path().join("settings.json");
        let mut store = Store::load(path.clone());
        store.settings.last_url = Endpoint::parse("localhost:3000/?token=do-not-persist")
            .unwrap()
            .saved
            .to_string();
        store.settings.language = LanguageSetting::En;
        store.save().unwrap();
        assert!(!fs::read_to_string(&path)
            .unwrap()
            .contains("do-not-persist"));
        assert_eq!(
            Store::load(path.clone()).settings.last_url,
            "http://localhost:3000/"
        );
        assert_eq!(
            Store::load(path.clone()).settings.language,
            LanguageSetting::En
        );
        // Replacing an existing file must work on Windows as well as Unix.
        store.settings.language = LanguageSetting::Ru;
        store.save().unwrap();
        assert_eq!(Store::load(path).settings.language, LanguageSetting::Ru);
        assert!(!directory.path().join("settings.json.tmp").exists());
    }

    #[test]
    fn corrupt_or_legacy_settings_are_safe() {
        let directory = tempfile::tempdir().unwrap();
        let path = directory.path().join("settings.json");
        fs::write(&path, "not json").unwrap();
        assert!(Store::load(path.clone()).settings.last_url.is_empty());
        fs::write(
            &path,
            r#"{"lastUrl":"http://localhost:3000/?token=old","width":1}"#,
        )
        .unwrap();
        let store = Store::load(path);
        assert_eq!(store.settings.last_url, "http://localhost:3000/");
        assert_eq!(store.settings.width, 640.0);
        assert_eq!(store.settings.language, LanguageSetting::System);
    }

    #[test]
    fn unchanged_saves_skip_io_and_failed_changes_can_be_retried() {
        let directory = tempfile::tempdir().unwrap();
        let path = directory.path().join("settings.json");
        let mut store = Store::load(path.clone());
        store.save().unwrap();
        // An unchanged save must not even attempt to replace this file.
        store.path = directory
            .path()
            .join("missing-parent")
            .join("settings.json");
        store.save().unwrap();
        assert!(!store.path.parent().unwrap().exists());

        // A failed write must not mark the new preference as saved.
        let blocked = directory.path().join("blocked");
        fs::write(&blocked, b"not a directory").unwrap();
        store.path = blocked.join("settings.json");
        store.settings.language = LanguageSetting::Ru;
        assert_eq!(store.save(), Err(AppError::SaveSettings));
        store.path = path.clone();
        store.save().unwrap();
        assert_eq!(Store::load(path).settings.language, LanguageSetting::Ru);
    }

    #[test]
    fn loaded_settings_are_scrubbed_before_the_first_save_is_skipped() {
        let directory = tempfile::tempdir().unwrap();
        let path = directory.path().join("settings.json");
        fs::write(
            &path,
            r#"{"lastUrl":"http://localhost:3000/?token=old","width":1}"#,
        )
        .unwrap();
        let mut store = Store::load(path.clone());
        store.save().unwrap();
        let content = fs::read_to_string(path).unwrap();
        assert!(!content.contains("token"));
        assert!(content.contains("640.0"));
    }
}
