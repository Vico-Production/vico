import { useState } from "react";
import { api, errorMessage } from "../lib/api";
import type { Health, Language, LanguageCapability, Settings } from "../lib/contracts";
import { LanguagePicker, Notice, Toggle } from "./common";

export function Onboarding({
  settings,
  capabilities,
  onDone,
}: {
  settings: Settings;
  capabilities: LanguageCapability[];
  onDone: (patch: Partial<Settings>) => Promise<void>;
}) {
  const [step, setStep] = useState(0);
  const [language, setLanguage] = useState<Language>(settings.language);
  const [consent, setConsent] = useState(settings.cloud_consent);
  const [geminiKey, setGeminiKey] = useState("");
  const [workspace, setWorkspace] = useState(settings.workspace);
  const [approval, setApproval] = useState(settings.require_approval);
  const [check, setCheck] = useState<Health | null>(null);
  const [error, setError] = useState<string | null>(null);

  const finish = async () => {
    setError(null);
    try {
      if (geminiKey.trim()) await api.saveSecret("gemini", geminiKey.trim());
      await onDone({ language, cloud_consent: consent, workspace, require_approval: approval, onboarding_complete: true });
    } catch (err) {
      setError(errorMessage(err));
    }
  };

  const selfCheck = async () => {
    setError(null);
    try {
      if (geminiKey.trim()) await api.saveSecret("gemini", geminiKey.trim());
      await api.updateSettings({ cloud_consent: consent, workspace });
      setCheck(await api.health());
    } catch (err) {
      setError(errorMessage(err));
    }
  };

  const steps = [
    <div key="welcome">
      <h2>Welcome to Vico</h2>
      <p>Speak or type in English, Yoruba, Hausa or Igbo, and Vico does things on this computer: files, apps, websites and more.</p>
      <ul className="plain">
        <li>Vico only listens after you press the microphone button, for up to 15 seconds. There is no always-on microphone.</li>
        <li>You see each action before it runs, unless you switch approval off.</li>
        <li>Vico never makes payments and never types passwords or card details.</li>
      </ul>
    </div>,
    <div key="language">
      <h2>Your language</h2>
      <LanguagePicker value={language} onChange={setLanguage} capabilities={capabilities} />
      <p className="muted small">
        Speech recognition for Yoruba, Hausa and Igbo is still being tested. You can always check and correct what Vico
        heard before anything runs.
      </p>
    </div>,
    <div key="cloud">
      <h2>Cloud processing</h2>
      <p>
        Understanding speech and free-form requests uses a free cloud AI service. When this is on, your voice clips, typed
        requests, and any file or web page text Vico reads during a task are sent to that service. Without it, Vico only
        understands simple typed English commands such as <code>create folder Demo</code>.
      </p>
      <Toggle label="Allow cloud processing" checked={consent} onChange={setConsent} testId="onboard-consent" />
      <div className="field">
        <span>Your free Gemini access code (you can also add it later in Settings)</span>
        <ol className="plain">
          <li>
            Open{" "}
            <a href="https://aistudio.google.com/apikey" target="_blank" rel="noreferrer">
              Google AI Studio
            </a>{" "}
            and sign in with your Google account.
          </li>
          <li>Press "Create API key" and copy it. It is free and needs no card.</li>
          <li>Paste it below.</li>
        </ol>
        <input
          type="password"
          autoComplete="off"
          aria-label="Gemini access code"
          placeholder="Paste your Gemini access code"
          value={geminiKey}
          onChange={(e) => setGeminiKey(e.target.value)}
        />
      </div>
      <p className="muted small">
        The code is stored in the Windows Credential Manager (or your system keyring), never in Vico's files. Google may
        use free-tier requests to improve its products.
      </p>
    </div>,
    <div key="workspace">
      <h2>Workspace and approval</h2>
      <label className="field">
        <span>Workspace folder for new files and notes</span>
        <input value={workspace} onChange={(e) => setWorkspace(e.target.value)} />
      </label>
      <Toggle
        label="Ask before each action (recommended)"
        description="You can change this any time in Settings. Deleting, running commands and sending always ask."
        checked={approval}
        onChange={setApproval}
      />
    </div>,
    <div key="check">
      <h2>Self-check</h2>
      <button className="btn" onClick={selfCheck} data-testid="self-check">
        Run self-check
      </button>
      {check && (
        <ul className="plain checks">
          <li>{check.online ? "✓ Internet reachable" : "✗ No internet: typed local commands only"}</li>
          <li>{check.cloud_ready ? "✓ Cloud planner ready" : "✗ Cloud planner not ready (add a key and allow cloud processing)"}</li>
          <li>{check.speech_ready ? "✓ Speech-to-text ready" : "✗ Speech not ready: you can type instead"}</li>
          <li>✓ Local engine running ({check.adapter})</li>
        </ul>
      )}
    </div>,
  ];

  return (
    <div className="overlay onboarding">
      <div className="drawer" role="dialog" aria-modal="true" aria-label="Set up Vico" data-testid="onboarding">
        <div className="drawer-body">
          <p className="muted small">
            Step {step + 1} of {steps.length}
          </p>
          {steps[step]}
          {error && <Notice kind="error">{error}</Notice>}
          <div className="row spread">
            <button className="btn ghost" onClick={() => setStep((s) => s - 1)} disabled={step === 0}>
              Back
            </button>
            {step < steps.length - 1 ? (
              <button className="btn primary" onClick={() => setStep((s) => s + 1)} data-testid="onboard-next">
                Next
              </button>
            ) : (
              <button className="btn primary" onClick={finish} data-testid="onboard-finish">
                Start using Vico
              </button>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
