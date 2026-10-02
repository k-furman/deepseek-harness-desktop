use url::Url;

pub fn initialization_script(server: &Url) -> String {
    let origin = serde_json::json!(server.origin().ascii_serialization()).to_string();
    include_str!("desktop_shell.js").replace("__DSH_ORIGIN__", &origin)
}
