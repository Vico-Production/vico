mod sidecar;

use serde_json::{json, Value};
use sidecar::Sidecar;
use std::sync::{Arc, Mutex};
use std::time::Duration;
use tauri::menu::{CheckMenuItem, Menu, MenuItem, PredefinedMenuItem};
use tauri::tray::{MouseButton, MouseButtonState, TrayIconBuilder, TrayIconEvent};
use tauri::{
    AppHandle, Emitter, Manager, PhysicalPosition, PhysicalSize, RunEvent, State, WebviewWindow,
    WindowEvent,
};
use tauri_plugin_autostart::{MacosLauncher, ManagerExt};
use tauri_plugin_global_shortcut::{Code, GlobalShortcutExt, Modifiers, Shortcut, ShortcutState};

/// Passed by the sign-in entry, so a login start stays quiet.
const AUTOSTART_ARG: &str = "--autostart";

struct AppState {
    sidecar: Arc<Sidecar>,
    http: reqwest::Client,
    autostarted: bool,
    shortcut: Mutex<String>, // the shortcut that was actually registered ("" if none)
}

const METHODS: [&str; 4] = ["GET", "POST", "PUT", "DELETE"];

// The prompt sits above the liquid pool at the bottom centre of the screen.
const PROMPT_WIDTH: f64 = 960.0;
const PROMPT_HEIGHT: f64 = 440.0;
const PROMPT_BOTTOM_GAP: f64 = 190.0;

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
        Err(_) => {
            return Ok(envelope_error(
                "sidecar_unavailable",
                "The Vico engine could not start.",
            ))
        }
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
            Err(_) => Ok(envelope_error(
                "internal",
                "The Vico engine sent an unreadable reply.",
            )),
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

#[tauri::command]
fn launch_info(state: State<'_, AppState>) -> Value {
    let shortcut = state.shortcut.lock().map(|s| s.clone()).unwrap_or_default();
    json!({ "autostart": state.autostarted, "shortcut": shortcut })
}

/// Size the aura to cover the whole primary screen and park the prompt above the pool.
fn place_windows(app: &AppHandle) {
    let Some(aura) = app.get_webview_window("aura") else {
        return;
    };
    let Ok(Some(monitor)) = aura.primary_monitor() else {
        return;
    };
    let origin = monitor.position();
    let size = monitor.size();
    let scale = monitor.scale_factor();
    let _ = aura.set_position(PhysicalPosition::new(origin.x, origin.y));
    let _ = aura.set_size(PhysicalSize::new(size.width, size.height));
    if let Some(prompt) = app.get_webview_window("prompt") {
        let width = ((PROMPT_WIDTH * scale) as u32).min(size.width);
        let height = (PROMPT_HEIGHT * scale) as u32;
        let x = origin.x + (size.width.saturating_sub(width) / 2) as i32;
        let y = origin.y + size.height as i32 - height as i32 - (PROMPT_BOTTOM_GAP * scale) as i32;
        let _ = prompt.set_size(PhysicalSize::new(width, height));
        let _ = prompt.set_position(PhysicalPosition::new(x, y.max(origin.y)));
    }
}

/// Show a window without taking keyboard focus from the app the user is working in.
fn show_without_focus(window: &WebviewWindow) {
    #[cfg(windows)]
    {
        use windows_sys::Win32::UI::WindowsAndMessaging::{ShowWindow, SW_SHOWNOACTIVATE};
        if let Ok(hwnd) = window.hwnd() {
            unsafe {
                ShowWindow(hwnd.0 as _, SW_SHOWNOACTIVATE);
            }
            return;
        }
    }
    let _ = window.show();
}

#[tauri::command]
fn aura_show(app: AppHandle) {
    if let Some(aura) = app.get_webview_window("aura") {
        let _ = aura.set_ignore_cursor_events(true);
        show_without_focus(&aura);
    }
}

#[tauri::command]
fn aura_hide(app: AppHandle) {
    if let Some(aura) = app.get_webview_window("aura") {
        let _ = aura.hide();
    }
}

#[tauri::command]
fn prompt_show(app: AppHandle) {
    if let Some(prompt) = app.get_webview_window("prompt") {
        let _ = prompt.show();
        let _ = prompt.set_focus();
    }
}

#[tauri::command]
fn prompt_hide(app: AppHandle) {
    if let Some(prompt) = app.get_webview_window("prompt") {
        let _ = prompt.hide();
    }
}

/// Bring Vico up: the aura starts glowing and the driver (in the aura window) is told why.
fn summon(app: &AppHandle, event: &str) {
    place_windows(app);
    aura_show(app.clone());
    let _ = app.emit(event, ());
}

fn shortcut_label(preferred: bool) -> &'static str {
    match (preferred, cfg!(target_os = "macos"), cfg!(windows)) {
        (true, true, _) => "Cmd + Option + V",
        (true, _, true) => "Win + Alt + V",
        (true, _, _) => "Super + Alt + V",
        (false, true, _) => "Ctrl + Option + V",
        (false, _, _) => "Ctrl + Alt + V",
    }
}

/// Win + Alt + V (Cmd + Option + V on macOS), or Ctrl + Alt + V if another app owns it.
/// Returns the label of the one registered, or "" when neither could be.
fn register_shortcut(app: &AppHandle) -> String {
    let preferred = Shortcut::new(Some(Modifiers::SUPER | Modifiers::ALT), Code::KeyV);
    if app.global_shortcut().register(preferred).is_ok() {
        return shortcut_label(true).to_string();
    }
    let fallback = Shortcut::new(Some(Modifiers::CONTROL | Modifiers::ALT), Code::KeyV);
    if app.global_shortcut().register(fallback).is_ok() {
        return shortcut_label(false).to_string();
    }
    String::new()
}

/// Start with the computer by default, once. After that the tray toggle decides.
fn autostart_enabled(app: &AppHandle) -> bool {
    let manager = app.autolaunch();
    if cfg!(debug_assertions) {
        return manager.is_enabled().unwrap_or(false); // never register a development build
    }
    if let Ok(dir) = app.path().app_config_dir() {
        let marker = dir.join("autostart-chosen");
        if !marker.exists() {
            let _ = manager.enable();
            let _ = std::fs::create_dir_all(&dir);
            let _ = std::fs::write(&marker, b"1");
        }
    }
    manager.is_enabled().unwrap_or(false)
}

fn build_tray(app: &AppHandle, shortcut: &str) -> tauri::Result<()> {
    let summon_label = if shortcut.is_empty() {
        "Summon Vico".to_string()
    } else {
        format!("Summon Vico   ({shortcut})")
    };
    let summon_item = MenuItem::with_id(app, "summon", summon_label, true, None::<&str>)?;
    let settings_item = MenuItem::with_id(
        app,
        "settings",
        "Settings and access codes",
        true,
        None::<&str>,
    )?;
    let autostart_item = CheckMenuItem::with_id(
        app,
        "autostart",
        "Start when I sign in",
        true,
        autostart_enabled(app),
        None::<&str>,
    )?;
    let quit_item = MenuItem::with_id(app, "quit", "Quit Vico", true, None::<&str>)?;
    let separator = PredefinedMenuItem::separator(app)?;
    let menu = Menu::with_items(
        app,
        &[
            &summon_item,
            &settings_item,
            &autostart_item,
            &separator,
            &quit_item,
        ],
    )?;
    let tooltip = if shortcut.is_empty() {
        "Vico".to_string()
    } else {
        format!("Vico · {shortcut}")
    };
    let mut tray = TrayIconBuilder::with_id("vico")
        .tooltip(tooltip)
        .menu(&menu)
        .show_menu_on_left_click(false)
        .on_menu_event(|app, event| match event.id().as_ref() {
            "summon" => summon(app, "vico://summon"),
            "settings" => summon(app, "vico://settings"),
            "autostart" => {
                // The check mark flips by itself; make the sign-in entry match it.
                let manager = app.autolaunch();
                let _ = if manager.is_enabled().unwrap_or(false) {
                    manager.disable()
                } else {
                    manager.enable()
                };
            }
            "quit" => app.exit(0),
            _ => {}
        })
        .on_tray_icon_event(|tray, event| {
            if let TrayIconEvent::Click {
                button: MouseButton::Left,
                button_state: MouseButtonState::Up,
                ..
            } = event
            {
                summon(tray.app_handle(), "vico://summon");
            }
        });
    if let Some(icon) = app.default_window_icon() {
        tray = tray.icon(icon.clone());
    }
    tray.build(app)?;
    Ok(())
}

pub fn run() {
    let sidecar = Arc::new(Sidecar::new());
    let http = reqwest::Client::builder()
        .no_proxy()
        .build()
        .expect("http client");
    let autostarted = std::env::args().any(|a| a == AUTOSTART_ARG);
    let app = tauri::Builder::default()
        .plugin(tauri_plugin_single_instance::init(|app, _args, _cwd| {
            summon(app, "vico://summon");
        }))
        .plugin(tauri_plugin_autostart::init(
            MacosLauncher::LaunchAgent,
            Some(vec![AUTOSTART_ARG]),
        ))
        .plugin(
            tauri_plugin_global_shortcut::Builder::new()
                .with_handler(|app, _shortcut, event| {
                    if event.state() == ShortcutState::Pressed {
                        summon(app, "vico://summon");
                    }
                })
                .build(),
        )
        .manage(AppState {
            sidecar: sidecar.clone(),
            http,
            autostarted,
            shortcut: Mutex::new(String::new()),
        })
        .setup(|app| {
            let state = app.state::<AppState>();
            let sidecar = state.sidecar.clone();
            sidecar.set_resource_dir(app.path().resource_dir().ok());
            std::thread::spawn(move || {
                let _ = sidecar.ensure_ready();
            });
            let handle = app.handle().clone();
            place_windows(&handle);
            let shortcut = register_shortcut(&handle);
            if let Ok(mut slot) = state.shortcut.lock() {
                slot.clone_from(&shortcut);
            }
            build_tray(&handle, &shortcut)?;
            Ok(())
        })
        .on_window_event(|window, event| {
            // Vico's windows are never closed, only hidden; Quit is in the tray menu.
            if let WindowEvent::CloseRequested { api, .. } = event {
                api.prevent_close();
                let _ = window.hide();
            }
        })
        .invoke_handler(tauri::generate_handler![
            api_request,
            sidecar_status,
            launch_info,
            aura_show,
            aura_hide,
            prompt_show,
            prompt_hide
        ])
        .build(tauri::generate_context!())
        .expect("error while building Vico");

    app.run(move |_handle, event| {
        if let RunEvent::Exit = event {
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
        assert!(valid_path("/agent/runs/current"));
        assert!(valid_path("/history?limit=10"));
        assert!(!valid_path("agent"));
        assert!(!valid_path("/../secrets"));
        assert!(!valid_path("//evil.example/x"));
        assert!(!valid_path("/x y"));
    }
}
