use serde::Serialize;

#[derive(Clone, Copy, Debug, PartialEq, Eq, Serialize)]
#[serde(rename_all = "camelCase")]
pub enum AppError {
    NotAllowed,
    InvalidAddress,
    InvalidHost,
    UnsupportedScheme,
    CredentialsInUrl,
    OpenConnection,
    OpenWindow,
    CancelConnection,
    #[cfg(target_os = "linux")]
    ConfigureDownloads,
    BrowserSession,
    ResetSession,
    #[cfg(not(target_os = "macos"))]
    BrowserProfile,
    ConfigureMenu,
    SaveSettings,
    OpenSettings,
    CheckConnection,
    Timeout,
    Unauthorized,
    Forbidden,
    ExternalRedirect,
    ServerError,
    TooManyRedirects,
    Tls,
    Network,
}
