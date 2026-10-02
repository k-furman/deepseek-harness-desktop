use serde::{Deserialize, Serialize};
use std::{collections::HashMap, sync::OnceLock};

#[derive(Clone, Copy, Debug, PartialEq, Eq, Serialize)]
#[serde(rename_all = "lowercase")]
pub enum Language {
    En,
    Ru,
}

#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, Deserialize, Serialize)]
#[serde(rename_all = "lowercase")]
pub enum LanguageSetting {
    #[default]
    System,
    En,
    Ru,
}

impl LanguageSetting {
    pub fn resolve(self, system: Language) -> Language {
        match self {
            Self::System => system,
            Self::En => Language::En,
            Self::Ru => Language::Ru,
        }
    }
}

#[derive(Deserialize)]
struct Catalog {
    menu: HashMap<String, String>,
    native: HashMap<String, String>,
}

impl Language {
    pub fn from_locale(locale: Option<&str>) -> Self {
        let primary = locale
            .unwrap_or_default()
            .trim()
            .split(['-', '_', '.', '@'])
            .next()
            .unwrap_or_default();
        if primary.eq_ignore_ascii_case("ru") {
            Self::Ru
        } else {
            Self::En
        }
    }

    pub fn system() -> Self {
        Self::from_locale(sys_locale::get_locale().as_deref())
    }

    fn catalog(self) -> &'static Catalog {
        static EN: OnceLock<Catalog> = OnceLock::new();
        static RU: OnceLock<Catalog> = OnceLock::new();
        let (cell, json) = match self {
            Self::En => (&EN, include_str!("../../src/locales/en.json")),
            Self::Ru => (&RU, include_str!("../../src/locales/ru.json")),
        };
        cell.get_or_init(|| serde_json::from_str(json).expect("bundled language catalog"))
    }

    pub fn menu(self, key: &str) -> &'static str {
        self.catalog()
            .menu
            .get(key)
            .expect("bundled menu translation")
    }

    pub fn native(self, key: &str) -> &'static str {
        self.catalog()
            .native
            .get(key)
            .expect("bundled native translation")
    }

    pub fn translated_menu_text(self, previous: &str) -> Option<&'static str> {
        Language::En
            .catalog()
            .menu
            .iter()
            .find_map(|(key, english)| {
                let russian = Language::Ru.menu(key);
                (previous == english || previous == russian).then(|| self.menu(key))
            })
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn system_language_matches_primary_subtag_and_falls_back_to_english() {
        for locale in ["ru", "ru-RU", "ru_RU.UTF-8", "RU-ru", "ru_RU@variant"] {
            assert_eq!(Language::from_locale(Some(locale)), Language::Ru);
        }
        for locale in [
            None,
            Some("en-GB"),
            Some("de-DE"),
            Some("zh-CN"),
            Some("C"),
            Some(""),
        ] {
            assert_eq!(Language::from_locale(locale), Language::En);
        }
        assert_eq!(LanguageSetting::default(), LanguageSetting::System);
        assert_eq!(LanguageSetting::System.resolve(Language::Ru), Language::Ru);
        assert_eq!(LanguageSetting::En.resolve(Language::Ru), Language::En);
        assert_eq!(LanguageSetting::Ru.resolve(Language::En), Language::Ru);
        assert!(serde_json::from_str::<LanguageSetting>("\"de\"").is_err());
    }

    #[test]
    fn native_catalogs_have_identical_keys_and_menu_text_can_switch_both_ways() {
        for section in [
            (&Language::En.catalog().menu, &Language::Ru.catalog().menu),
            (
                &Language::En.catalog().native,
                &Language::Ru.catalog().native,
            ),
        ] {
            assert_eq!(section.0.len(), section.1.len());
            assert!(section.0.keys().all(|key| section.1.contains_key(key)));
        }
        for key in Language::En.catalog().menu.keys() {
            assert_eq!(
                Language::Ru.translated_menu_text(Language::En.menu(key)),
                Some(Language::Ru.menu(key))
            );
            assert_eq!(
                Language::En.translated_menu_text(Language::Ru.menu(key)),
                Some(Language::En.menu(key))
            );
        }
    }
}
