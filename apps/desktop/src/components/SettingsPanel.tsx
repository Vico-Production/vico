import { useEffect, useState } from "react";
import { api, errorMessage } from "../lib/api";
import type { Health, ProviderName, Settings } from "../lib/contracts";
import { Drawer, Notice, Toggle } from "./common";

const PROVIDERS = [
  {
    id: "groq",
    name: "GroqCloud",
    keyUrl: "https://console.groq.com/keys",
    privacy: "https://groq.com/privacy-policy/",
    note: "Free plan with rate limits. Speech-to-text (Whisper) and chat models.",
  },
  {
    id: "gemini",
    name: "Google Gemini API",
    keyUrl: "https://aistudio.google.com/apikey",
    privacy: "https://ai.google.dev/gemini-api/terms",
    note: "Free tier on some models; Google may use free-tier data to improve products. Check the terms.",
  },
] as const;

export function SettingsPanel({
  settings,
  health,
  onSave,
  onClose,
}: {
  settings: Settings;
  health: Health | null;
  onSave: (patch: Partial<Settings>) => Promise<void>;
  onClose: () => void;
}) {
  const [keys, setKeys] = useState<Record<string, string>>({});
  const [configured, setConfigured] = useState<Record<string, boolean>>({});
  const [models, setModels] = useState<Record<string, string[]>>({});
  const [message, setMessage] = useState<{ kind: "ok" | "error"; text: string } | null>(null);
  const [roots, setRoots] = useState(settings.allowed_roots.join("\n"));
  const [workspace, setWorkspace] = useState(settings.workspace);

  useEffect(() => {
    api.secrets().then(setConfigured).catch(() => undefined);
  }, []);

  const run = async (fn: () => Promise<unknown>, ok: string) => {
    setMessage(null);
    try {
      await fn();
      setMessage({ kind: "ok", text: ok });
    } catch (err) {
      setMessage({ kind: "error", text: errorMessage(err) });
    }
  };

  const saveKey = (id: string) =>
    run(async () => {
      await api.saveSecret(id, keys[id] ?? "");
      setKeys((k) => ({ ...k, [id]: "" }));
      setConfigured(await api.secrets());
    }, "Key saved in the system credential store.");

  const removeKey = (id: string) =>
    run(async () => {
      await api.deleteSecret(id);
      setConfigured(await api.secrets());
    }, "Key removed.");

  const loadModels = (id: string) =>
    run(async () => {
      const res = await api.models(id);
      setModels((m) => ({ ...m, [id]: res.models }));
    }, "Loaded the models your account can use.");

  const set = (patch: Partial<Settings>) => run(() => onSave(patch), "Saved.");

  const roleModels = (provider: ProviderName) => (provider === "none" ? [] : models[provider] ?? []);

  return (
    <Drawer title="Settings" onClose={onClose} testId="settings">
      {message && <Notice kind={message.kind}>{message.text}</Notice>}

      <section className="settings-section">
        <h3>Safety</h3>
        <Toggle
          label="Ask before each action"
          description="On: every step that changes something waits for your approval. Off: ordinary steps run on their own. Deleting, running commands, uploading files and sending/posting always ask either way. Payments and passwords are never done."
          checked={settings.require_approval}
          onChange={(v) => set({ require_approval: v })}
          testId="approval-switch"
        />
        <Toggle
          label="Let sends, posts and form submissions run without asking"
          description="Only applies when approval is off. Leave this off unless you are sure."
          checked={settings.allow_send_without_approval}
          onChange={(v) => set({ allow_send_without_approval: v })}
        />
      </section>

      <section className="settings-section">
        <h3>Cloud processing</h3>
        <Toggle
          label="Allow cloud processing"
          description="Your voice clips, typed requests, and file or page text Vico reads during a task are sent to the provider below. Nothing is sent while this is off; typed offline commands still work."
          checked={settings.cloud_consent}
          onChange={(v) => set({ cloud_consent: v })}
          testId="cloud-consent"
        />
        <Toggle
          label="Use the other provider if the first one fails"
          description="Only when both have keys. Data then goes to the second provider too."
          checked={settings.fallback_consent}
          onChange={(v) => set({ fallback_consent: v })}
        />
        {PROVIDERS.map((p) => (
          <div className="provider" key={p.id}>
            <div className="provider-head">
              <strong>{p.name}</strong>
              <span className={`badge ${configured[p.id] ? "ok" : ""}`}>
                {configured[p.id] ? "key saved" : "no key"}
                {health?.providers[p.id] ? ` · ${health.providers[p.id].requests_today}/${health.providers[p.id].daily_budget} today` : ""}
              </span>
            </div>
            <p className="muted small">
              {p.note} Get a free key at <a href={p.keyUrl} target="_blank" rel="noreferrer">{p.keyUrl}</a>. Data use:{" "}
              <a href={p.privacy} target="_blank" rel="noreferrer">
                terms
              </a>
              .
            </p>
            <div className="row">
              <label className="sr-only" htmlFor={`key-${p.id}`}>
                {p.name} API key
              </label>
              <input
                id={`key-${p.id}`}
                type="password"
                autoComplete="off"
                placeholder={configured[p.id] ? "Replace the saved key" : "Paste API key"}
                value={keys[p.id] ?? ""}
                onChange={(e) => setKeys((k) => ({ ...k, [p.id]: e.target.value }))}
                data-testid={`key-${p.id}`}
              />
              <button className="btn" disabled={(keys[p.id] ?? "").length < 8} onClick={() => saveKey(p.id)}>
                Save key
              </button>
              {configured[p.id] && (
                <>
                  <button className="btn ghost" onClick={() => removeKey(p.id)}>
                    Remove
                  </button>
                  <button className="btn ghost" disabled={!settings.cloud_consent} onClick={() => loadModels(p.id)}>
                    List models
                  </button>
                </>
              )}
            </div>
          </div>
        ))}
        <div className="grid2">
          <RoleSelect label="Speech-to-text" value={settings.stt_provider} onChange={(v) => set({ stt_provider: v, stt_model: null })} />
          <ModelSelect label="Speech model" value={settings.stt_model} options={roleModels(settings.stt_provider)} onChange={(v) => set({ stt_model: v })} />
          <RoleSelect label="Planning & translation" value={settings.llm_provider} onChange={(v) => set({ llm_provider: v, llm_model: null })} />
          <ModelSelect label="Chat model" value={settings.llm_model} options={roleModels(settings.llm_provider)} onChange={(v) => set({ llm_model: v })} />
        </div>
        <label className="field">
          <span>Daily request budget (stops before free limits run out)</span>
          <input
            type="number"
            min={1}
            max={100000}
            defaultValue={settings.daily_request_budget}
            onBlur={(e) => set({ daily_request_budget: Math.max(1, Number(e.target.value) || 1) })}
          />
        </label>
      </section>

      <section className="settings-section">
        <h3>Folders</h3>
        <label className="field">
          <span>Workspace (where relative paths and new notes go)</span>
          <input value={workspace} onChange={(e) => setWorkspace(e.target.value)} onBlur={() => set({ workspace })} />
        </label>
        <label className="field">
          <span>Folders Vico may use (one per line; ~ means your home folder)</span>
          <textarea
            rows={3}
            value={roots}
            onChange={(e) => setRoots(e.target.value)}
            onBlur={() => set({ allowed_roots: roots.split("\n").map((r) => r.trim()).filter(Boolean) })}
          />
        </label>
        <p className="muted small">System folders such as Windows and Program Files are always protected from changes.</p>
      </section>

      <section className="settings-section">
        <h3>Agent</h3>
        <label className="field">
          <span>Maximum steps per task</span>
          <input type="number" min={1} max={40} defaultValue={settings.max_steps} onBlur={(e) => set({ max_steps: Math.min(40, Math.max(1, Number(e.target.value) || 1)) })} />
        </label>
        <label className="field">
          <span>Browser Vico controls</span>
          <select value={settings.browser_channel} onChange={(e) => set({ browser_channel: e.target.value as Settings["browser_channel"] })}>
            <option value="auto">Automatic (Edge, then Chrome)</option>
            <option value="msedge">Microsoft Edge</option>
            <option value="chrome">Google Chrome</option>
            <option value="chromium">Bundled Chromium (needs download)</option>
          </select>
        </label>
        <p className="muted small">
          Vico uses its own browser profile, separate from your everyday one. It never types passwords or card details.
        </p>
        {health?.browser_open && (
          <button className="btn" onClick={() => run(() => api.closeBrowser(), "Browser closed.")}>
            Close Vico's browser
          </button>
        )}
      </section>
    </Drawer>
  );
}

function RoleSelect({ label, value, onChange }: { label: string; value: ProviderName; onChange: (v: ProviderName) => void }) {
  return (
    <label className="field">
      <span>{label}</span>
      <select value={value} onChange={(e) => onChange(e.target.value as ProviderName)}>
        <option value="groq">GroqCloud</option>
        <option value="gemini">Google Gemini</option>
        <option value="none">None (offline only)</option>
      </select>
    </label>
  );
}

function ModelSelect({
  label,
  value,
  options,
  onChange,
}: {
  label: string;
  value: string | null;
  options: string[];
  onChange: (v: string | null) => void;
}) {
  return (
    <label className="field">
      <span>{label}</span>
      <select value={value ?? ""} onChange={(e) => onChange(e.target.value || null)}>
        <option value="">Automatic (from your account's model list)</option>
        {value && !options.includes(value) && <option value={value}>{value}</option>}
        {options.map((m) => (
          <option key={m} value={m}>
            {m}
          </option>
        ))}
      </select>
    </label>
  );
}
