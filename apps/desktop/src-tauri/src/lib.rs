mod sidecar;

use serde_json::{json, Value};
use sidecar::Sidecar;
use std::sync::Arc;
use std::time::Duration;
use tauri::{Manager, RunEvent, State};

struct AppState {
    sidecar: Arc<Sidecar>,
    http: reqwest::Client,
}

const METHODS: [&str; 4] = ["GET", "POST", "PUT", "DELETE"];

fn envelope_error(code: &str, message: &str) -> Value {
    json!({
        "api_version": "1",
        "ok": false,
        "data": null,
        "error": { "code": code, "message": message, "retryable": true, "retry_after_s": null }
    })
}

fn valid_path(path: &str) -> bool {
    path.starts_with('/')
        && path.len() < 300
        && !path.contains("..")
        && !path.contains("//")
        && path
            .chars()
            .all(|c| c.is_ascii_alphanumeric() || "/-_?=&.".contains(c))
}

/// Proxy a UI request to the local engine. The launch token is added here and never
/// leaves the Rust process.
#[tauri::command]
async fn api_request(
    state: State<'_, AppState>,
    method: String,
    path: String,
    body: Option<Value>,
) -> Result<Value, String> {
    if !METHODS.contains(&method.as_str()) || !valid_path(&path) {
        return Ok(envelope_error("validation_error", "Invalid request."));
    }
    let sidecar = state.sidecar.clone();
    let port = match tauri::async_runtime::spawn_blocking(move || sidecar.ensure_ready()).await {
        Ok(Ok(port)) => port,
        Ok(Err(message)) => return Ok(envelope_error("sidecar_unavailable", &message)),
        Err(_) => return Ok(envelope_error("sidecar_unavailable", "The Vico engine could not start.")),
    };
    let url = format!("http://127.0.0.1:{port}/api/v1{path}");
    let method = reqwest::Method::from_bytes(method.as_bytes()).map_err(|e| e.to_string())?;
    let mut request = state
        .http
        .request(method, url)
        .bearer_auth(state.sidecar.token())
        .timeout(Duration::from_secs(150));
    if let Some(body) = body {
        request = request.json(&body);
    }
    match request.send().await {
        Ok(response) => match response.json::<Value>().await {
            Ok(value) => Ok(value),
            Err(_) => Ok(envelope_error("internal", "The Vico engine sent an unreadable reply.")),
        },
        Err(err) => {
            if err.is_connect() {
                state.sidecar.mark_unreachable();
            }
            let message = if err.is_timeout() {
                "The Vico engine took too long to answer."
            } else {
                "The Vico engine stopped responding. It will restart on the next request."
            };
            Ok(envelope_error("sidecar_unavailable", message))
        }
    }
}

#[tauri::command]
fn sidecar_status(state: State<'_, AppState>) -> Value {
    state.sidecar.status()
}

pub fn run() {
    let sidecar = Arc::new(Sidecar::new());
    let http = reqwest::Client::builder()
        .no_proxy()
        .build()
        .expect("http client");
    let app = tauri::Builder::default()
        .manage(AppState { sidecar: sidecar.clone(), http })
        .setup(|app| {
            let state = app.state::<AppState>();
            let sidecar = state.sidecar.clone();
            let resource_dir = app.path().resource_dir().ok();
            sidecar.set_resource_dir(resource_dir);
            std::thread::spawn(move || {
                let _ = sidecar.ensure_ready();
            });
            Ok(())
        })
        .invoke_handler(tauri::generate_handler![api_request, sidecar_status])
        .build(tauri::generate_context!())
        .expect("error while building Vico");

    app.run(move |_handle, event| {
        if let RunEvent::Exit | RunEvent::ExitRequested { .. } = event {
            sidecar.shutdown();
        }
    });
}

#[cfg(test)]
mod tests {
    use super::valid_path;

    #[test]
    fn path_validation() {
        assert!(valid_path("/agent/runs/abc123/decision"));
        assert!(valid_path("/history?limit=10"));
        assert!(!valid_path("agent"));
        assert!(!valid_path("/../secrets"));
        assert!(!valid_path("//evil.example/x"));
        assert!(!valid_path("/x y"));
    }
}
