# Platform plan

Order: **Windows first, Linux second (same codebase), macOS later.** Everything that differs by OS sits behind `PlatformAdapter` (`services/agent/app/platform/`), so adding a platform means adding an adapter, not changing the agent.

| Capability | Windows | Linux | macOS |
|---|---|---|---|
| Installer | NSIS `.exe`, `.msi` | `.deb`, `.rpm`, `.AppImage` | planned `.dmg` |
| Open files / folders | `os.startfile` | `xdg-open` | `open` |
| Find and launch apps | built-ins + Start Menu shortcuts | built-ins + `.desktop` entries | `/Applications` bundles |
| List / focus windows | Win32 API | `wmctrl` (X11) | not yet |
| Type / press keys | pywinauto | `xdotool` (X11) | not yet |
| Click a named control | pywinauto UI Automation | not available | not yet |
| Password-field check before typing | UI Automation `IsPassword` | not available (card-number check still applies) | not yet |
| Shell | PowerShell (or cmd/bash) | bash / sh | bash / sh |
| Browser control | installed Edge, then Chrome | installed Chrome, else downloaded Chromium | planned |
| API key storage | Credential Manager | Secret Service (GNOME Keyring / KWallet) | Keychain |
| Microphone | PortAudio (bundled in wheel) | PortAudio (`libportaudio2`) | PortAudio |

## Linux notes

- **Wayland** blocks one app from typing into or focusing another by design. On Wayland, desktop input tools report "not supported" and Vico uses files, apps, browser and shell tools instead.
- The `.deb` declares `libportaudio2`, `xdotool` and `wmctrl` as dependencies.
- Without Chrome, run `uv run playwright install chromium` once (about 150 MB). Vico never downloads it silently.
- Linux has not yet been tested on real hardware; CI builds and runs the test suite on Ubuntu.

## Release checklist per platform

- [ ] Clean install, first launch, onboarding, quit, relaunch, uninstall
- [ ] Engine starts within a few seconds (it ships as a PyInstaller one-dir folder; the shell waits up to 120 s)
- [ ] Typed offline `create folder Demo`
- [ ] One spoken English action
- [ ] Browser: open a page, read it, click a link
- [ ] Memory measured with `scripts/doctor.ps1` (Windows) or `ps -o rss` (Linux)
- [ ] Code signing (Windows Authenticode; optional Linux GPG) — not set up yet
