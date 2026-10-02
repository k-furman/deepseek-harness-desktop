use crate::endpoint::{cookie_matches, same_origin};
use crate::error::AppError;
use std::{future::Future, sync::Arc, time::Duration};
use tauri::webview::Cookie;
use tokio::{sync::OnceCell, time::Instant};
use url::Url;

pub const TIMEOUT_ERROR: AppError = AppError::Timeout;

#[derive(Clone, Default)]
pub struct Probe {
    client: Arc<OnceCell<reqwest::Client>>,
}

impl Probe {
    async fn client(&self) -> Result<&reqwest::Client, AppError> {
        self.client
            .get_or_try_init(|| async {
                // Loading platform TLS roots may block. Reuse the resulting client
                // across transport checks, verification and later connections.
                tokio::task::spawn_blocking(|| {
                    reqwest::Client::builder()
                        .redirect(reqwest::redirect::Policy::none())
                        .build()
                        .map_err(|_| AppError::CheckConnection)
                })
                .await
                .map_err(|_| AppError::CheckConnection)?
            })
            .await
    }

    // WKWebView does not emit Finished for a failed provisional TLS navigation.
    // Check transport only: the launch token and cookies stay out of this request.
    // HTTP authorization is checked later against the real WebView cookie session.
    pub async fn check_transport(&self, url: Url, timeout: Duration) -> Result<(), AppError> {
        tokio::time::timeout(timeout, async {
            self.client()
                .await?
                .get(url)
                .timeout(timeout)
                .send()
                .await
                .map(|_| ())
                .map_err(network_error)
        })
        .await
        .unwrap_or(Err(TIMEOUT_ERROR))
    }

    pub async fn verify<F, Fut>(
        &self,
        url: Url,
        timeout: Duration,
        mut cookies_for_url: F,
    ) -> Result<(), AppError>
    where
        F: FnMut(Url) -> Fut,
        Fut: Future<Output = Result<Vec<Cookie<'static>>, AppError>>,
    {
        let deadline = Instant::now() + timeout;
        tokio::time::timeout_at(deadline, async {
            let client = self.client().await?;
            let origin = url.clone();
            let mut current = url;
            for _ in 0..5 {
                // A redirect may leave a cookie's Path scope or enter another one.
                // Ask the WebView for this URL's session on every allowed hop.
                let cookies = cookies_for_url(current.clone()).await?;
                let header = cookies
                    .iter()
                    .filter(|cookie| cookie_matches(cookie, &current))
                    .map(|cookie| format!("{}={}", cookie.name(), cookie.value()))
                    .collect::<Vec<_>>()
                    .join("; ");
                let remaining = deadline.saturating_duration_since(Instant::now());
                if remaining.is_zero() {
                    return Err(TIMEOUT_ERROR);
                }
                let mut request = client.get(current.clone()).timeout(remaining);
                if !header.is_empty() {
                    let mut value = reqwest::header::HeaderValue::from_str(&header)
                        .map_err(|_| AppError::BrowserSession)?;
                    value.set_sensitive(true);
                    request = request.header(reqwest::header::COOKIE, value);
                }
                let response = request.send().await.map_err(network_error)?;
                match response.status().as_u16() {
                    200..=299 => return Ok(()),
                    401 => return Err(AppError::Unauthorized),
                    403 => return Err(AppError::Forbidden),
                    300..=399 => {
                        let next = response
                            .headers()
                            .get(reqwest::header::LOCATION)
                            .and_then(|header| header.to_str().ok())
                            .and_then(|location| current.join(location).ok())
                            .filter(|next| same_origin(&origin, next))
                            .ok_or(AppError::ExternalRedirect)?;
                        current = next;
                    }
                    _ => return Err(AppError::ServerError),
                }
            }
            Err(AppError::TooManyRedirects)
        })
        .await
        .unwrap_or(Err(TIMEOUT_ERROR))
    }
}

fn network_error(error: reqwest::Error) -> AppError {
    if error.is_timeout() {
        return TIMEOUT_ERROR;
    }
    // Inspect only for categorization, never expose a reqwest error containing a URL.
    let mut source: Option<&(dyn std::error::Error + 'static)> = Some(&error);
    while let Some(cause) = source {
        let message = cause.to_string().to_lowercase();
        if message.contains("certificate") || message.contains("tls") || message.contains("ssl") {
            return AppError::Tls;
        }
        source = cause.source();
    }
    AppError::Network
}

#[cfg(test)]
mod tests {
    use super::*;
    use tokio::{
        io::{AsyncReadExt, AsyncWriteExt},
        net::TcpListener,
        task::JoinHandle,
    };

    async fn server(responses: Vec<&'static str>) -> (Url, JoinHandle<Vec<String>>) {
        let listener = TcpListener::bind("127.0.0.1:0").await.unwrap();
        let url = Url::parse(&format!("http://{}/", listener.local_addr().unwrap())).unwrap();
        let task = tokio::spawn(async move {
            let mut requests = Vec::new();
            for response in responses {
                let request = tokio::time::timeout(Duration::from_secs(5), async {
                    let (mut stream, _) = listener.accept().await.unwrap();
                    let mut request = Vec::new();
                    let mut buffer = [0; 1024];
                    while !request.windows(4).any(|part| part == b"\r\n\r\n") {
                        let read = stream.read(&mut buffer).await.unwrap();
                        assert!(read > 0 && request.len() < 8192);
                        request.extend_from_slice(&buffer[..read]);
                    }
                    stream.write_all(response.as_bytes()).await.unwrap();
                    String::from_utf8(request).unwrap()
                })
                .await
                .unwrap();
                requests.push(request);
            }
            requests
        });
        (url, task)
    }

    #[tokio::test]
    async fn redirects_read_cookies_for_each_path() {
        let (mut url, requests) = server(vec![
            "HTTP/1.1 302 Found\r\nLocation: /other\r\nContent-Length: 0\r\nConnection: close\r\n\r\n",
            "HTTP/1.1 200 OK\r\nContent-Length: 0\r\nConnection: close\r\n\r\n",
        ])
        .await;
        url.set_path("/start");
        let mut visited = Vec::new();
        let result = Probe::default()
            .verify(url, Duration::from_secs(5), |current| {
                visited.push(current.path().to_owned());
                let cookies = vec![
                    Cookie::build(("initial", "start")).path("/start").build(),
                    Cookie::build(("next", "other")).path("/other").build(),
                    Cookie::build(("foreign", "excluded"))
                        .domain("other.example")
                        .build(),
                    Cookie::build(("secure", "excluded")).secure(true).build(),
                ];
                async move { Ok(cookies) }
            })
            .await;
        assert_eq!(result, Ok(()));
        assert_eq!(visited, ["/start", "/other"]);
        let requests = requests.await.unwrap();
        assert!(requests[0].contains("cookie: initial=start\r\n"));
        assert!(requests[1].contains("cookie: next=other\r\n"));
        for request in requests {
            assert!(!request.contains("excluded"));
        }
    }

    #[tokio::test]
    async fn external_redirect_is_rejected_before_reading_another_session() {
        let (url, requests) = server(vec![
            "HTTP/1.1 302 Found\r\nLocation: http://other.example/private\r\nContent-Length: 0\r\nConnection: close\r\n\r\n",
        ])
        .await;
        let mut calls = 0;
        let result = Probe::default()
            .verify(url, Duration::from_secs(5), |_| {
                calls += 1;
                async { Ok(Vec::new()) }
            })
            .await;
        assert_eq!(result, Err(AppError::ExternalRedirect));
        assert_eq!(calls, 1);
        assert_eq!(requests.await.unwrap().len(), 1);
    }

    #[tokio::test]
    async fn verification_classifies_http_failures() {
        for (response, expected) in [
            (
                "HTTP/1.1 401 Unauthorized\r\nContent-Length: 0\r\nConnection: close\r\n\r\n",
                AppError::Unauthorized,
            ),
            (
                "HTTP/1.1 403 Forbidden\r\nContent-Length: 0\r\nConnection: close\r\n\r\n",
                AppError::Forbidden,
            ),
            (
                "HTTP/1.1 500 Internal Server Error\r\nContent-Length: 0\r\nConnection: close\r\n\r\n",
                AppError::ServerError,
            ),
        ] {
            let (url, requests) = server(vec![response]).await;
            let result = Probe::default()
                .verify(url, Duration::from_secs(5), |_| async { Ok(Vec::new()) })
                .await;
            assert_eq!(result, Err(expected));
            requests.await.unwrap();
        }
    }

    #[tokio::test]
    async fn transport_check_does_not_require_authorization_or_send_cookies() {
        let (url, requests) = server(vec![
            "HTTP/1.1 401 Unauthorized\r\nContent-Length: 0\r\nConnection: close\r\n\r\n",
        ])
        .await;
        assert_eq!(
            Probe::default()
                .check_transport(url, Duration::from_secs(5))
                .await,
            Ok(())
        );
        let request = requests.await.unwrap().pop().unwrap();
        assert!(!request.contains("cookie:"));
        assert!(!request.contains("authorization:"));
    }

    #[tokio::test]
    async fn verification_deadline_includes_reading_browser_cookies() {
        let probe = Probe::default();
        probe.client().await.unwrap();
        let result = probe
            .verify(
                Url::parse("http://127.0.0.1:9/").unwrap(),
                Duration::from_millis(20),
                |_| async {
                    std::future::pending::<()>().await;
                    Ok(Vec::new())
                },
            )
            .await;
        assert_eq!(result, Err(AppError::Timeout));
    }
}
