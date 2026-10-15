mod lens;
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
    // The last window the user worked in that is not Vico's own (Windows: HWND; Linux: geometry).
    foreground: Mutex<(isize, Option<(i32, i32, i32, i32)>)>,
}

const METHODS: [&str; 4] = ["GET", "POST", "PUT", "DELETE"];

// Before the UI places it next to the chosen look, the prompt waits at the bottom centre.
const PROMPT_WIDTH: f64 = 460.0;
const PROMPT_HEIGHT: f64 = 138.0;
const PROMPT_BOTTOM_GAP: f64 = 120.0;

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

/// The primary screen's work area (the screen minus the taskbar): origin, size and scale.
/// Vico's looks live inside it, so Peek stands on the taskbar instead of hiding behind it.
fn work_area(app: &AppHandle) -> Option<(PhysicalPosition<i32>, PhysicalSize<u32>, f64)> {
    let aura = app.get_webview_window("aura")?;
    let monitor = aura.primary_monitor().ok()??;
    let area = monitor.work_area();
    Some((area.position, area.size, monitor.scale_factor()))
}

/// Size the aura to cover the work area and park the prompt near the bottom centre.
fn place_windows(app: &AppHandle) {
    let Some(aura) = app.get_webview_window("aura") else {
        return;
    };
    let Some((origin, size, scale)) = work_area(app) else {
        return;
    };
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

/// Put the prompt next to the chosen look. Coordinates are CSS pixels of the aura window.
#[tauri::command]
fn prompt_frame(app: AppHandle, x: f64, y: f64, width: f64, height: f64) {
    let Some(prompt) = app.get_webview_window("prompt") else {
        return;
    };
    let Some((origin, _, scale)) = work_area(&app) else {
        return;
    };
    let _ = prompt.set_size(PhysicalSize::new(
        (width * scale).round() as u32,
        (height * scale).round() as u32,
    ));
    let _ = prompt.set_position(PhysicalPosition::new(
        origin.x + (x * scale).round() as i32,
        origin.y + (y * scale).round() as i32,
    ));
}

/// The window the user is working in (never Vico's own), in CSS pixels of the aura window.
/// Peek walks towards it and Possession lights it up. Null when it cannot be known
/// (Wayland, macOS for now, or no ordinary window in front).
#[tauri::command]
fn foreground_rect(app: AppHandle) -> Option<Value> {
    let (origin, _, scale) = work_area(&app)?;
    let (x, y, w, h) = native_foreground(&app)?;
    Some(json!({
        "x": (x - origin.x) as f64 / scale,
        "y": (y - origin.y) as f64 / scale,
        "width": w as f64 / scale,
        "height": h as f64 / scale,
    }))
}

#[cfg(windows)]
fn native_foreground(app: &AppHandle) -> Option<(i32, i32, i32, i32)> {
    use windows_sys::Win32::Foundation::{HWND, RECT};
    use windows_sys::Win32::Graphics::Dwm::{DwmGetWindowAttribute, DWMWA_EXTENDED_FRAME_BOUNDS};
    use windows_sys::Win32::UI::WindowsAndMessaging::{
        GetClassNameW, GetForegroundWindow, GetWindowRect, IsIconic, IsWindowVisible,
    };

    // Vico's own windows, the desktop and the taskbar never count as "the app in use".
    let ours: Vec<isize> = ["aura", "prompt"]
        .iter()
        .filter_map(|label| app.get_webview_window(label))
        .filter_map(|window| window.hwnd().ok())
        .map(|hwnd| hwnd.0 as isize)
        .collect();
    let shell = |hwnd: HWND| -> bool {
        let mut buf = [0u16; 64];
        let len = unsafe { GetClassNameW(hwnd, buf.as_mut_ptr(), buf.len() as i32) };
        let class = String::from_utf16_lossy(&buf[..len.max(0) as usize]);
        matches!(
            class.as_str(),
            "Progman"
                | "WorkerW"
                | "Shell_TrayWnd"
                | "Shell_SecondaryTrayWnd"
                | "NotifyIconOverflowWindow"
        )
    };

    let state = app.state::<AppState>();
    let mut memo = state.foreground.lock().ok()?;
    let current = unsafe { GetForegroundWindow() };
    if !current.is_null() && !ours.contains(&(current as isize)) && !shell(current) {
        memo.0 = current as isize;
    }
    let hwnd = memo.0 as HWND;
    if hwnd.is_null() {
        return None;
    }
    unsafe {
        if IsWindowVisible(hwnd) == 0 || IsIconic(hwnd) != 0 {
            return None;
        }
        let mut rect = RECT {
            left: 0,
            top: 0,
            right: 0,
            bottom: 0,
        };
        // The extended frame excludes the invisible resize borders Windows adds around windows.
        let framed = DwmGetWindowAttribute(
            hwnd,
            DWMWA_EXTENDED_FRAME_BOUNDS as u32,
            &mut rect as *mut RECT as *mut core::ffi::c_void,
            std::mem::size_of::<RECT>() as u32,
        ) == 0;
        if !framed && GetWindowRect(hwnd, &mut rect) == 0 {
            return None;
        }
        Some((
            rect.left,
            rect.top,
            rect.right - rect.left,
            rect.bottom - rect.top,
        ))
    }
}

#[cfg(target_os = "linux")]
fn native_foreground(app: &AppHandle) -> Option<(i32, i32, i32, i32)> {
    // X11 only (xdotool); on Wayland this fails and Vico falls back to its home position.
    let run = |args: &[&str]| -> Option<String> {
        let out = std::process::Command::new("xdotool")
            .args(args)
            .output()
            .ok()?;
        out.status
            .success()
            .then(|| String::from_utf8_lossy(&out.stdout).into_owned())
    };
    let state = app.state::<AppState>();
    let mut memo = state.foreground.lock().ok()?;
    let name = run(&["getactivewindow", "getwindowname"]).unwrap_or_default();
    if name.trim() != "Vico" {
        if let Some(text) = run(&["getactivewindow", "getwindowgeometry", "--shell"]) {
            let get = |key: &str| {
                text.lines()
                    .find_map(|line| line.strip_prefix(key)?.trim().parse::<i32>().ok())
            };
            if let (Some(x), Some(y), Some(w), Some(h)) =
                (get("X="), get("Y="), get("WIDTH="), get("HEIGHT="))
            {
                memo.1 = Some((x, y, w, h));
            }
        }
    }
    memo.1
}

#[cfg(not(any(windows, target_os = "linux")))]
fn native_foreground(_app: &AppHandle) -> Option<(i32, i32, i32, i32)> {
    None
}

/// Work-area origin (physical pixels) and scale, so the UI can turn the screen positions the
/// engine reports for each step into its own CSS pixels.
#[tauri::command]
fn aura_metrics(app: AppHandle) -> Option<Value> {
    let (origin, _, scale) = work_area(&app)?;
    Some(json!({ "x": origin.x, "y": origin.y, "scale": scale }))
}

/// The aura lets every click through, except while the cursor is over Vico's handle
/// (Peek's hands, the yo-yo's anchor) so it can be dragged.
#[tauri::command]
fn aura_interactive(app: AppHandle, on: bool) {
    if let Some(aura) = app.get_webview_window("aura") {
        let _ = aura.set_ignore_cursor_events(!on);
    }
}

/// While Vico is on screen, tell the aura where the mouse is (in its CSS pixels), so the
/// avatar can dodge a slowing cursor and offer its handle. A click-through window cannot see
/// the mouse by itself.
fn watch_cursor(app: AppHandle) {
    std::thread::spawn(move || {
        let mut last = (f64::NAN, f64::NAN);
        loop {
            std::thread::sleep(Duration::from_millis(40));
            let Some(aura) = app.get_webview_window("aura") else {
                continue;
            };
            if !aura.is_visible().unwrap_or(false) {
                continue;
            }
            let (Ok(pos), Some((origin, _, scale))) = (app.cursor_position(), work_area(&app))
            else {
                continue;
            };
            let x = (pos.x - origin.x as f64) / scale;
            let y = (pos.y - origin.y as f64) / scale;
            if (x - last.0).abs() < 0.5 && (y - last.1).abs() < 0.5 {
                continue;
            }
            last = (x, y);
            let _ = app.emit_to("aura", "vico://cursor", json!({ "x": x, "y": y }));
        }
    });
}

/// Vico's own windows (never captured by the Lens, never "the app in use").
fn own_windows(app: &AppHandle) -> Vec<isize> {
    #[cfg(windows)]
    {
        ["aura", "prompt"]
            .iter()
            .filter_map(|label| app.get_webview_window(label))
            .filter_map(|window| window.hwnd().ok())
            .map(|hwnd| hwnd.0 as isize)
            .collect()
    }
    #[cfg(not(windows))]
    {
        let _ = app;
        Vec::new()
    }
}

/// Show the Lens (centre and radius in the aura's CSS pixels). False when the real screen
/// cannot be magnified here, so the UI draws clear glass and says so instead of faking it.
#[tauri::command]
fn lens_show(app: AppHandle, x: f64, y: f64, radius: f64, zoom: f64) -> bool {
    let Some((origin, _, scale)) = work_area(&app) else {
        return false;
    };
    let px = origin.x + (x * scale).round() as i32;
    let py = origin.y + (y * scale).round() as i32;
    let r = (radius * scale).round() as i32;
    let exclude = own_windows(&app);
    let (tx, rx) = std::sync::mpsc::channel();
    // Windows must be created and moved on the thread that runs the event loop.
    let _ = app.run_on_main_thread(move || {
        let _ = tx.send(lens::show(px, py, r, zoom as f32, &exclude));
    });
    rx.recv_timeout(Duration::from_millis(500)).unwrap_or(false)
}

#[tauri::command]
fn lens_hide(app: AppHandle) {
    let _ = app.run_on_main_thread(lens::hide);
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
        &[&summon_item, &autostart_item, &separator, &quit_item],
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
            foreground: Mutex::new((0, None)),
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
            watch_cursor(handle.clone());
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
            prompt_frame,
            foreground_rect,
            aura_metrics,
            aura_interactive,
            lens_show,
            lens_hide,
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
