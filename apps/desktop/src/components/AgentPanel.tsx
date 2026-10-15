import { useState } from "react";
import { api } from "../lib/api";
import { LANGUAGE_NAMES, TERMINAL_STATES, type Health, type Language, type LanguageCapability, type Settings } from "../lib/contracts";
import { useRecorder, useRun } from "../lib/hooks";
import { ActionPreview } from "./ActionPreview";
import { CooldownNotice } from "./Cooldown";
import { LanguagePicker, Notice } from "./common";
import { MicControl } from "./MicControl";
import { StepList } from "./StepList";
import { Timeline } from "./Timeline";

const EXAMPLES = [
  "Create a folder called Hackathon",
  "Find my attendance notes and open them",
  "Open Notepad",
  "Open bbc.com/news and tell me the top headline",
];

export function AgentPanel({
  settings,
  health,
  capabilities,
  onLanguage,
}: {
  settings: Settings;
  health: Health | null;
  capabilities: LanguageCapability[];
  onLanguage: (lang: Language) => void;
}) {
  const language = settings.language;
  const [text, setText] = useState("");
  const [heard, setHeard] = useState<string | null>(null);
  const [answer, setAnswer] = useState("");
  const { run, setRun, error, setError, guard } = useRun();
  const [busy, setBusy] = useState(false);
  const recorder = useRecorder((t) => {
    setText(t.text);
    setHeard(`Heard via ${t.provider} in ${(t.latency_ms / 1000).toFixed(1)}s. Check the words, fix anything wrong, then press Run.`);
  });

  const active = run && !TERMINAL_STATES.includes(run.state);
  const pending = run?.pending_step_id ? run.steps.find((s) => s.id === run.pending_step_id) : undefined;
  const speechReady = Boolean(health?.speech_ready);

  const submit = async () => {
    const value = text.trim();
    if (!value || active) return;
    setHeard(null);
    setBusy(true);
    await guard(() => api.startRun(value, language));
    setBusy(false);
  };

  const decide = async (approved: boolean, confirm = false) => {
    if (!run || !pending) return;
    setBusy(true);
    await guard(() => api.decide(run.id, pending.id, approved, confirm));
    setBusy(false);
  };

  const reply = async () => {
    if (!run || !answer.trim()) return;
    await guard(() => api.reply(run.id, answer.trim()));
    setAnswer("");
  };

  const reset = () => {
    setRun(null);
    setText("");
    setError(null);
  };

  return (
    <div className="panel agent" data-testid="agent-panel">
      <section className="card input-card" aria-label="Your request">
        <LanguagePicker value={language} onChange={onLanguage} capabilities={capabilities} label="Language you speak or type" disabled={Boolean(active)} />
        <div className="input-row">
          <MicControl
            phase={recorder.phase}
            status={recorder.status}
            onStart={() => recorder.start(language)}
            onStop={recorder.stop}
            onCancel={recorder.cancel}
            disabled={!speechReady || Boolean(active) || recorder.blocked}
            disabledReason={
              !speechReady
                ? health?.online === false
                  ? "Offline: type a command instead."
                  : "Set up a speech provider in Settings, or type instead."
                : recorder.blocked
                  ? "Wait for speech playback to finish."
                  : undefined
            }
          />
          <div className="transcript">
            <label htmlFor="request-text" className="label">
              {heard ? "What Vico heard (you can edit it)" : `Type or speak in ${LANGUAGE_NAMES[language]}`}
            </label>
            <textarea
              id="request-text"
              value={text}
              lang={language}
              onChange={(e) => setText(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) {
                  e.preventDefault();
                  void submit();
                }
              }}
              placeholder={EXAMPLES[0]}
              rows={3}
              maxLength={2000}
              disabled={Boolean(active)}
              data-testid="request-input"
            />
            {heard && <p className="muted small">{heard}</p>}
            <div className="row">
              <button className="btn primary" onClick={submit} disabled={!text.trim() || Boolean(active) || busy} data-testid="run-button">
                Run <kbd>Ctrl+Enter</kbd>
              </button>
              {active && (
                <button className="btn" onClick={() => guard(() => api.cancel(run!.id))} data-testid="cancel-run">
                  Cancel task
                </button>
              )}
              {run && !active && (
                <button className="btn ghost" onClick={reset}>
                  New task
                </button>
              )}
            </div>
          </div>
        </div>
        {recorder.error && <Notice kind="error">{recorder.error}</Notice>}
        {!run && (
          <div className="examples" aria-label="Examples">
            {EXAMPLES.map((ex) => (
              <button key={ex} className="chip small" onClick={() => setText(ex)} disabled={Boolean(active)}>
                {ex}
              </button>
            ))}
          </div>
        )}
      </section>

      {error && <Notice kind="error">{error}</Notice>}

      {run && (
        <section className="card run" aria-label="Task progress" aria-live="polite">
          <div className="run-head">
            <Timeline run={run} />
            <span className={`badge ${run.mode}`} title={run.mode === "offline" ? "Using the local typed-command parser" : "Using the cloud planner"}>
              {run.mode === "offline" ? "Local only" : "Cloud planner"}
            </span>
          </div>
          {run.canonical && run.canonical !== run.text && (
            <p className="muted">
              Understood as: <em>{run.canonical}</em>
            </p>
          )}
          {run.state === "cooling_down" && run.cooldown_until && <CooldownNotice until={run.cooldown_until} />}
          {pending && (
            <ActionPreview step={pending} busy={busy} onApprove={(c) => decide(true, c)} onReject={() => decide(false)} />
          )}
          {run.state === "awaiting_clarification" && run.question && (
            <div className="card clarify" data-testid="clarify-card">
              <label htmlFor="clarify-answer">
                <strong>Vico asks:</strong> {run.question}
              </label>
              <div className="row">
                <input
                  id="clarify-answer"
                  value={answer}
                  onChange={(e) => setAnswer(e.target.value)}
                  onKeyDown={(e) => e.key === "Enter" && reply()}
                  autoFocus
                />
                <button className="btn primary" onClick={reply} disabled={!answer.trim()}>
                  Answer
                </button>
              </div>
            </div>
          )}
          <StepList steps={run.steps} />
          {run.state === "completed" && run.message && (
            <Notice kind="ok">
              {run.message_localized && <p lang={run.language}>{run.message_localized}</p>}
              <p>{run.message}</p>
            </Notice>
          )}
          {(run.state === "failed" || run.state === "cancelled") && run.message && (
            <Notice kind={run.state === "failed" ? "error" : "info"}>{run.message}</Notice>
          )}
        </section>
      )}
    </div>
  );
}
