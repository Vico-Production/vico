# Third-party notices

Vico uses the following open-source components. Each keeps its own license; full texts ship with the packages (`node_modules/*/LICENSE`, Python package metadata, Cargo registry sources). Versions are pinned in `services/agent/uv.lock`, `apps/desktop/package-lock.json` and `apps/desktop/src-tauri/Cargo.lock`.

Regenerate a complete inventory before each release:

```bash
cd services/agent && uv run pip-licenses --format=markdown      # needs: uv add --dev pip-licenses
cd apps/desktop && npx license-checker --summary
cd apps/desktop/src-tauri && cargo install cargo-about && cargo about generate about.hbs
```

## Direct dependencies

| Component | Use | License |
|---|---|---|
| Tauri 2 (+ tauri-build) | desktop shell | MIT OR Apache-2.0 |
| reqwest, serde, serde_json, getrandom | Rust shell HTTP, JSON, randomness | MIT OR Apache-2.0 |
| React, React DOM | UI | MIT |
| Vite, @vitejs/plugin-react | bundler | MIT |
| TypeScript | language | Apache-2.0 |
| Vitest, Testing Library, jsdom | UI tests (dev only) | MIT |
| FastAPI, Starlette | engine HTTP API | MIT / BSD-3-Clause |
| Uvicorn | engine server | BSD-3-Clause |
| Pydantic | strict validation | MIT |
| HTTPX | provider HTTP client | BSD-3-Clause |
| keyring | OS credential store | MIT |
| Send2Trash | recoverable deletion | BSD-3-Clause |
| python-sounddevice (bundles PortAudio) | microphone capture | MIT (PortAudio: MIT-style) |
| Playwright for Python (bundles a Node.js driver) | browser control | Apache-2.0 |
| pywinauto (+ comtypes, pywin32) | Windows desktop control | BSD-3-Clause / MIT / PSF |
| pytest, ruff, mypy, PyInstaller | development and packaging | MIT / MIT / MIT / GPL-2.0 with bootloader exception |

PyInstaller's bootloader exception allows distributing the packaged engine under any license.

## Cloud services (optional, not bundled)

- **GroqCloud API** — used under the user's own free account and Groq's terms.
- **Google Gemini API** — used under the user's own account and Google's Gemini API terms. Free-tier data may be used by Google to improve its products.

No model weights are bundled. CC-BY-NC models (for example NLLB-200) are **not** used.
