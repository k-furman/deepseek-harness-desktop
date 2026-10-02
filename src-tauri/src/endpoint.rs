use crate::error::AppError;
use url::Url;

#[derive(Clone)]
pub struct Endpoint {
    pub launch: Url,
    pub saved: Url,
}

impl Endpoint {
    pub fn parse(address: &str) -> Result<Self, AppError> {
        let address = address.trim();
        if address.is_empty() || address.len() > 8192 || address.chars().any(char::is_control) {
            return Err(AppError::InvalidAddress);
        }
        let normalized = if address.contains("://") {
            address.to_owned()
        } else {
            format!("http://{address}")
        };
        let launch = Url::parse(&normalized).map_err(|_| AppError::InvalidHost)?;
        if !matches!(launch.scheme(), "http" | "https") || launch.host_str().is_none() {
            return Err(AppError::UnsupportedScheme);
        }
        if !launch.username().is_empty() || launch.password().is_some() {
            return Err(AppError::CredentialsInUrl);
        }
        let mut saved = launch.clone();
        // Settings contain the endpoint only. Query strings and fragments may hold secrets.
        saved.set_query(None);
        saved.set_fragment(None);
        Ok(Self { launch, saved })
    }
}

pub fn same_origin(left: &Url, right: &Url) -> bool {
    matches!(right.scheme(), "http" | "https")
        && right.username().is_empty()
        && right.password().is_none()
        && left.origin() == right.origin()
}

pub fn bundled_origin(url: &Url, windows: bool) -> bool {
    // WebView2 maps Tauri's custom protocol to this HTTP origin. Keep the
    // scheme/host/port exact; ordinary server content never becomes local UI.
    let (scheme, host) = if windows {
        ("http", "tauri.localhost")
    } else {
        ("tauri", "localhost")
    };
    url.scheme() == scheme
        && url.host_str() == Some(host)
        && url.port().is_none()
        && url.username().is_empty()
        && url.password().is_none()
}

pub fn cookie_matches(cookie: &tauri::webview::Cookie<'_>, url: &Url) -> bool {
    let host = url.host_str().unwrap_or_default().trim_matches(['[', ']']);
    let domain = cookie
        .domain()
        .unwrap_or(host)
        .trim_start_matches('.')
        .trim_matches(['[', ']']);
    let domain_matches =
        host == domain || (url.domain().is_some() && host.ends_with(&format!(".{domain}")));
    let path = cookie.path().unwrap_or("/");
    let path_matches = url.path() == path
        || (url.path().starts_with(path)
            && (path.ends_with('/') || url.path()[path.len()..].starts_with('/')));
    domain_matches && path_matches && (!cookie.secure().unwrap_or(false) || url.scheme() == "https")
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn bundled_navigation_is_platform_specific_and_rejects_lookalikes() {
        assert!(bundled_origin(
            &Url::parse("http://tauri.localhost/index.html").unwrap(),
            true
        ));
        assert!(bundled_origin(
            &Url::parse("tauri://localhost/preferences.html").unwrap(),
            false
        ));
        assert!(!bundled_origin(
            &Url::parse("http://tauri.localhost/").unwrap(),
            false
        ));
        assert!(!bundled_origin(
            &Url::parse("tauri://localhost/").unwrap(),
            true
        ));
        for address in [
            "https://tauri.localhost/",
            "http://tauri.localhost:3000/",
            "http://tauri.localhost.example/",
            "http://evil.tauri.localhost/",
            "http://user@tauri.localhost/",
            "http://localhost:3000/",
        ] {
            assert!(
                !bundled_origin(&Url::parse(address).unwrap(), true),
                "{address}"
            );
        }
        assert!(!bundled_origin(
            &Url::parse("tauri://localhost:3000/").unwrap(),
            false
        ));
    }

    #[test]
    fn normalizes_address_and_preserves_auth_authority() {
        let endpoint = Endpoint::parse(" localhost:3000/?token=launch-secret ").unwrap();
        assert_eq!(
            endpoint.launch.as_str(),
            "http://localhost:3000/?token=launch-secret"
        );
        assert_eq!(endpoint.saved.as_str(), "http://localhost:3000/");
        assert!(!same_origin(
            &endpoint.saved,
            &Url::parse("http://127.0.0.1:3000").unwrap()
        ));
        assert!(!same_origin(
            &endpoint.saved,
            &Url::parse("http://localhost:3001").unwrap()
        ));
    }

    #[test]
    fn saves_base_path_but_no_secrets() {
        let endpoint =
            Endpoint::parse("https://server.example/harness/?token=a&key=b#secret").unwrap();
        assert_eq!(endpoint.saved.as_str(), "https://server.example/harness/");
        assert!(Endpoint::parse("http://user:password@server.example").is_err());
    }

    #[test]
    fn same_origin_navigation_rejects_embedded_credentials() {
        let origin = Url::parse("http://localhost:3000/app/").unwrap();
        for address in [
            "http://user@localhost:3000/next/",
            "http://user:password@localhost:3000/next/",
            "http://:password@localhost:3000/next/",
        ] {
            assert!(!same_origin(&origin, &Url::parse(address).unwrap()));
        }
        assert!(same_origin(
            &origin,
            &Url::parse("http://localhost:3000/next/").unwrap()
        ));
    }

    #[test]
    fn rejects_invalid_addresses_without_echoing_input() {
        for input in [
            "",
            "file:///secret",
            "javascript:alert(1)",
            "http://localhost:99999",
            "http://",
            "http://localhost\n/?token=sensitive",
        ] {
            let error = serde_json::to_string(&Endpoint::parse(input).err().unwrap()).unwrap();
            assert!(!error.contains(input) || input.is_empty());
            assert!(!error.contains("sensitive"));
        }
        assert!(Endpoint::parse("http://[::1]:3000/?token=test").is_ok());
    }

    #[test]
    fn filters_cookie_domain_path_and_security() {
        let url = Url::parse("http://localhost:3000/app").unwrap();
        let cookie = tauri::webview::Cookie::build(("session", "private"))
            .domain("localhost")
            .path("/")
            .http_only(true)
            .build();
        assert!(cookie_matches(&cookie, &url));
        assert!(!cookie_matches(
            &cookie,
            &Url::parse("http://otherhost:3000/").unwrap()
        ));
        let secure = tauri::webview::Cookie::build(("secure", "private"))
            .secure(true)
            .build();
        assert!(!cookie_matches(&secure, &url));
        let scoped = tauri::webview::Cookie::build(("scoped", "private"))
            .path("/app")
            .build();
        assert!(!cookie_matches(
            &scoped,
            &Url::parse("http://localhost:3000/apple").unwrap()
        ));
        for (domain, address) in [
            ("127.0.0.1", "http://127.0.0.1:3000/"),
            ("::1", "http://[::1]:3000/"),
        ] {
            let cookie = tauri::webview::Cookie::build(("ip_session", "private"))
                .domain(domain)
                .build();
            assert!(cookie_matches(&cookie, &Url::parse(address).unwrap()));
            assert!(!cookie_matches(&cookie, &url));
        }
    }
}
