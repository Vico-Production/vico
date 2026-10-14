import { useCallback, useEffect, useState } from "react";
import { AgentPanel } from "./components/AgentPanel";
import { Notice } from "./components/common";
import { HistoryPanel } from "./components/HistoryPanel";
import { InterpreterPanel } from "./components/InterpreterPanel";
import { Onboarding } from "./components/Onboarding";
import { SettingsPanel } from "./components/SettingsPanel";
import { api, errorMessage } from "./lib/api";
import type { Health, LanguageCapability, Settings } from "./lib/contracts";
import { useInterval } from "./lib/hooks";

type Mode = "agent" | "interpreter";

function StatusBadge({ health, error }: { health: Health | null; error: string | null }) {
  let label = "Starting…";
  let kind = "pending";
  let detail = "";
  if (error) {
    label = "Engine not responding";
    kind = "error";
    detail = error;
  } else if (health) {
    if (!health.online) {
      label = "Offline · local commands only";
      kind = "offline";
      detail = "Cloud unavailable; limited local typed commands only.";
    } else if (health.cloud_ready) {
      label = "Cloud connected";
      kind = "online";
      detail = "Requests are processed by your cloud provider.";
    } else {
      label = health.cloud_consent ? "Cloud not set up" : "Cloud off · local only";
      kind = "offline";
      detail = "Add an API key and allow cloud processing in Settings.";
    }
  }
  return (
    <span className={`status ${kind}`} role="status" title={detail} data-testid="status-badge">
      <span className="dot" aria-hidden="true" />
      {label}
    </span>
  );
}

export default function App() {
  const [mode, setMode] = useState<Mode>("agent");
  const [settings, setSettings] = useState<Settings | null>(null);
  const [health, setHealth] = useState<Health | null>(null);
  const [healthError, setHealthError] = useState<string | null>(null);
  const [capabilities, setCapabilities] = useState<LanguageCapability[]>([]);
  const [panel, setPanel] = useState<"settings" | "history" | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      const [s, langs] = await Promise.all([api.settings(), api.languages()]);
      setSettings(s);
      setCapabilities(langs);
      setLoadError(null);
    } catch (err) {
      setLoadError(errorMessage(err));
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  useInterval(() => {
    api
      .health()
      .then((h) => {
        setHealth(h);
        setHealthError(null);
        if (!settings) void load();
      })
      .catch((err) => setHealthError(errorMessage(err)));
  }, 5000);

  const save = useCallback(async (patch: Partial<Settings>) => {
    const next = await api.updateSettings(patch);
    setSettings(next);
    setHealth(await api.health().catch(() => null));
  }, []);

  const quietSave = (patch: Partial<Settings>) => {
    void save(patch).catch((err) => setLoadError(errorMessage(err)));
  };

  if (!settings) {
    return (
      <main className="boot" aria-busy={!loadError}>
        <h1 className="brand">Vico</h1>
        {loadError ? (
          <>
            <Notice kind="error">Vico's local engine did not start: {loadError}</Notice>
            <button className="btn primary" onClick={load}>
              Try again
            </button>
          </>
        ) : (
          <p className="muted">Starting the local engine…</p>
        )}
      </main>
    );
  }

  return (
    <div className="app">
      <header className="topbar">
        <h1 className="brand">Vico</h1>
        <nav className="segmented" aria-label="Mode">
          <button aria-pressed={mode === "agent"} className={mode === "agent" ? "active" : ""} onClick={() => setMode("agent")} data-testid="mode-agent">
            Agent
          </button>
          <button
            aria-pressed={mode === "interpreter"}
            className={mode === "interpreter" ? "active" : ""}
            onClick={() => setMode("interpreter")}
            data-testid="mode-interpreter"
          >
            Interpreter
          </button>
        </nav>
        <div className="topbar-right">
          <StatusBadge health={health} error={healthError} />
          <span className={`approval-pill ${settings.require_approval ? "on" : "off"}`} title="Change in Settings">
            {settings.require_approval ? "Approval on" : "Approval off"}
          </span>
          <button className="btn ghost" onClick={() => setPanel("history")} data-testid="open-history">
            History
          </button>
          <button className="btn ghost" onClick={() => setPanel("settings")} data-testid="open-settings">
            Settings
          </button>
        </div>
      </header>

      <main className="content">
        {loadError && <Notice kind="error">{loadError}</Notice>}
        {mode === "agent" ? (
          <AgentPanel settings={settings} health={health} capabilities={capabilities} onLanguage={(language) => quietSave({ language })} />
        ) : (
          <InterpreterPanel settings={settings} health={health} onChange={quietSave} />
        )}
      </main>

      {panel === "settings" && <SettingsPanel settings={settings} health={health} onSave={save} onClose={() => setPanel(null)} />}
      {panel === "history" && <HistoryPanel onClose={() => setPanel(null)} />}
      {!settings.onboarding_complete && <Onboarding settings={settings} capabilities={capabilities} onDone={save} />}
    </div>
  );
}
