//! The Lens look: a round window that shows the real screen under it, magnified, through the
//! Windows Magnification API (the same one Windows' own Magnifier uses). Vico's own windows are
//! excluded from what it magnifies. It never takes the mouse or the keyboard.
//!
//! Elsewhere (Linux, macOS, or if Windows refuses), `show` returns false and the Lens is drawn as
//! clear glass without magnification; the app says so instead of faking it.

#[cfg(windows)]
mod imp {
    use std::ptr::{null, null_mut};
    use std::sync::Mutex;
    use windows_sys::core::w;
    use windows_sys::Win32::Foundation::{HWND, RECT};
    use windows_sys::Win32::Graphics::Gdi::{CreateEllipticRgn, InvalidateRect, SetWindowRgn};
    use windows_sys::Win32::System::LibraryLoader::GetModuleHandleW;
    use windows_sys::Win32::UI::Magnification::{
        MagInitialize, MagSetWindowFilterList, MagSetWindowSource, MagSetWindowTransform,
        MAGTRANSFORM, MW_FILTERMODE_EXCLUDE, WC_MAGNIFIER,
    };
    use windows_sys::Win32::UI::WindowsAndMessaging::{
        CreateWindowExW, DefWindowProcW, DestroyWindow, RegisterClassW, SetLayeredWindowAttributes,
        SetWindowPos, ShowWindow, HWND_TOPMOST, LWA_ALPHA, SWP_NOACTIVATE, SWP_NOZORDER,
        SWP_SHOWWINDOW, SW_HIDE, WNDCLASSW, WS_CHILD, WS_EX_LAYERED, WS_EX_NOACTIVATE,
        WS_EX_TOOLWINDOW, WS_EX_TOPMOST, WS_EX_TRANSPARENT, WS_POPUP, WS_VISIBLE,
    };

    struct Lens {
        host: isize,
        mag: isize,
        size: i32,
    }

    enum State {
        Untried,
        Ready(Lens),
        Unavailable,
    }

    static LENS: Mutex<State> = Mutex::new(State::Untried);

    unsafe fn create(exclude: &[isize]) -> Option<Lens> {
        if MagInitialize() == 0 {
            return None;
        }
        let hinstance = GetModuleHandleW(null());
        let class = w!("VicoLensHost");
        let wc = WNDCLASSW {
            style: 0,
            lpfnWndProc: Some(DefWindowProcW),
            cbClsExtra: 0,
            cbWndExtra: 0,
            hInstance: hinstance,
            hIcon: null_mut(),
            hCursor: null_mut(),
            hbrBackground: null_mut(),
            lpszMenuName: null(),
            lpszClassName: class,
        };
        RegisterClassW(&wc);
        // Click-through, never activated, always on top, no taskbar button.
        let host = CreateWindowExW(
            WS_EX_TOPMOST | WS_EX_LAYERED | WS_EX_TRANSPARENT | WS_EX_TOOLWINDOW | WS_EX_NOACTIVATE,
            class,
            w!("Vico lens"),
            WS_POPUP,
            0,
            0,
            10,
            10,
            null_mut(),
            null_mut(),
            hinstance,
            null(),
        );
        if host.is_null() {
            return None;
        }
        SetLayeredWindowAttributes(host, 0, 255, LWA_ALPHA);
        let mag = CreateWindowExW(
            0,
            WC_MAGNIFIER,
            w!("VicoLensMagnifier"),
            WS_CHILD | WS_VISIBLE,
            0,
            0,
            10,
            10,
            host,
            null_mut(),
            hinstance,
            null(),
        );
        if mag.is_null() {
            DestroyWindow(host);
            return None;
        }
        // Never magnify Vico itself (its glass rim, bubbles, or this window).
        let mut skip: Vec<HWND> = exclude.iter().map(|h| *h as HWND).collect();
        skip.push(host);
        MagSetWindowFilterList(
            mag,
            MW_FILTERMODE_EXCLUDE,
            skip.len() as i32,
            skip.as_mut_ptr(),
        );
        Some(Lens {
            host: host as isize,
            mag: mag as isize,
            size: 0,
        })
    }

    /// Centre (x, y) and radius in physical screen pixels. False if magnifying is unavailable.
    pub fn show(x: i32, y: i32, radius: i32, zoom: f32, exclude: &[isize]) -> bool {
        let Ok(mut state) = LENS.lock() else {
            return false;
        };
        if matches!(*state, State::Untried) {
            *state = match unsafe { create(exclude) } {
                Some(lens) => State::Ready(lens),
                None => State::Unavailable,
            };
        }
        let State::Ready(lens) = &mut *state else {
            return false;
        };
        let (host, mag) = (lens.host as HWND, lens.mag as HWND);
        let d = (radius * 2).max(8);
        unsafe {
            if lens.size != d {
                SetWindowPos(
                    host,
                    HWND_TOPMOST,
                    x - radius,
                    y - radius,
                    d,
                    d,
                    SWP_NOACTIVATE | SWP_SHOWWINDOW,
                );
                SetWindowPos(mag, null_mut(), 0, 0, d, d, SWP_NOACTIVATE | SWP_NOZORDER);
                SetWindowRgn(host, CreateEllipticRgn(0, 0, d + 1, d + 1), 1);
                lens.size = d;
            } else {
                SetWindowPos(
                    host,
                    HWND_TOPMOST,
                    x - radius,
                    y - radius,
                    d,
                    d,
                    SWP_NOACTIVATE | SWP_SHOWWINDOW,
                );
            }
            let zoom = zoom.clamp(1.0, 4.0);
            let mut transform = MAGTRANSFORM {
                v: [zoom, 0.0, 0.0, 0.0, zoom, 0.0, 0.0, 0.0, 1.0],
            };
            MagSetWindowTransform(mag, &mut transform);
            let half = ((radius as f32) / zoom) as i32;
            MagSetWindowSource(
                mag,
                RECT {
                    left: x - half,
                    top: y - half,
                    right: x + half,
                    bottom: y + half,
                },
            );
            InvalidateRect(mag, null(), 1);
        }
        true
    }

    pub fn hide() {
        if let Ok(state) = LENS.lock() {
            if let State::Ready(lens) = &*state {
                unsafe {
                    ShowWindow(lens.host as HWND, SW_HIDE);
                }
            }
        }
    }
}

#[cfg(not(windows))]
mod imp {
    pub fn show(_x: i32, _y: i32, _radius: i32, _zoom: f32, _exclude: &[isize]) -> bool {
        false // no screen magnifier here: the Lens is clear glass, and the app says so
    }

    pub fn hide() {}
}

pub use imp::{hide, show};
