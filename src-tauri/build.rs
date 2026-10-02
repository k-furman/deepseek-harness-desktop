fn main() {
    tauri_build::try_build(tauri_build::Attributes::new().app_manifest(
        tauri_build::AppManifest::new().commands(&[
            "get_snapshot",
            "connect",
            "cancel_connect",
            "open_preferences",
            "get_preferences",
            "set_language",
            "close_preferences",
        ]),
    ))
    .expect("failed to build application manifest");
}
