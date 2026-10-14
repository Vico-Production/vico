import { useEffect, useState } from "react";
import { api, errorMessage } from "../lib/api";
import { LANGUAGE_NAMES, type Health, type Settings, type Translation } from "../lib/contracts";
import { useRecorder } from "../lib/hooks";
import { loadVoices, speak, stopSpeaking, voiceFor } from "../lib/speech";
import { LanguageSelect, Notice } from "./common";
import { MicControl } from "./MicControl";

interface Turn extends Translation {
  id: number;
}

export function InterpreterPanel({
  settings,
  health,
  onChange,
}: {
  settings: Settings;
  health: Health | null;
  onChange: (patch: Partial<Settings>) => void;
}) {
  const source = settings.interpreter_source;
  const target = settings.interpreter_target;
  const [text, setText] = useState("");
  const [turns, setTurns] = useState<Turn[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [, setVoicesReady] = useState(false);
  const recorder = useRecorder((t) => setText(t.text));

  useEffect(() => {
    void loadVoices().then(() => setVoicesReady(true));
    return () => stopSpeaking();
  }, []);

  const swap = () => {
    onChange({ interpreter_source: target, interpreter_target: source });
    setText("");
  };

  const translate = async () => {
    const value = text.trim();
    if (!value) return;
    setBusy(true);
    setError(null);
    try {
      const result = await api.translate(value, source, target);
      setTurns((prev) => [{ ...result, id: Date.now() }, ...prev]);
      setText("");
    } catch (err) {
      setError(`${errorMessage(err)} Your text is still in the box.`);
    } finally {
      setBusy(false);
    }
  };

  const cloudReady = Boolean(health?.cloud_ready);
  const targetVoice = voiceFor(target);

  return (
    <div className="panel interpreter" data-testid="interpreter-panel">
      <Notice kind="info">
        Turn-based machine translation. It can be wrong, especially for Yoruba, Hausa and Igbo, and it is not a
        professional interpreter. Turns are not saved.
      </Notice>
      <section className="card">
        <div className="lang-pair">
          <LanguageSelect id="src-lang" label="From" value={source} onChange={(l) => onChange({ interpreter_source: l })} />
          <button className="btn ghost swap" onClick={swap} aria-label="Swap languages" data-testid="swap-languages">
            ⇄
          </button>
          <LanguageSelect id="dst-lang" label="To" value={target} onChange={(l) => onChange({ interpreter_target: l })} />
        </div>
        <div className="input-row">
          <MicControl
            phase={recorder.phase}
            status={recorder.status}
            onStart={() => recorder.start(source)}
            onStop={recorder.stop}
            onCancel={recorder.cancel}
            disabled={!health?.speech_ready || recorder.blocked}
            disabledReason={recorder.blocked ? "Wait for playback to finish." : "Speech needs a cloud provider. Type instead."}
          />
          <div className="transcript">
            <label htmlFor="interp-text" className="label">
              {LANGUAGE_NAMES[source]} speaker: speak or type, then check the words
            </label>
            <textarea
              id="interp-text"
              lang={source}
              value={text}
              rows={3}
              maxLength={2000}
              onChange={(e) => setText(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) {
                  e.preventDefault();
                  void translate();
                }
              }}
              data-testid="interp-input"
            />
            <div className="row">
              <button className="btn primary" onClick={translate} disabled={!text.trim() || busy || !cloudReady} data-testid="translate-button">
                {busy ? "Translating…" : "Translate"}
              </button>
              {turns.length > 0 && (
                <button className="btn ghost" onClick={() => setTurns([])}>
                  Clear conversation
                </button>
              )}
            </div>
            {!cloudReady && (
              <p className="muted small">Translation needs the internet and a cloud provider set up in Settings.</p>
            )}
          </div>
        </div>
        {recorder.error && <Notice kind="error">{recorder.error}</Notice>}
        {error && <Notice kind="error">{error}</Notice>}
      </section>

      <ol className="turns" aria-label="Conversation" aria-live="polite">
        {turns.map((turn) => {
          const voice = voiceFor(turn.target);
          return (
            <li key={turn.id} className="card turn" data-testid="turn">
              <div className="pane">
                <small>{LANGUAGE_NAMES[turn.source]}</small>
                <p lang={turn.source}>{turn.original}</p>
              </div>
              <div className="pane out">
                <small>{LANGUAGE_NAMES[turn.target]}</small>
                <p lang={turn.target}>{turn.text}</p>
              </div>
              <div className="row">
                <button className="btn" onClick={() => navigator.clipboard?.writeText(turn.text)}>
                  Copy
                </button>
                {voice ? (
                  <button className="btn" onClick={() => speak(turn.text, turn.target)}>
                    Speak ({voice.name})
                  </button>
                ) : (
                  <span className="muted small">
                    No {LANGUAGE_NAMES[turn.target]} voice is installed on this computer, so only text is shown.
                  </span>
                )}
                <span className="muted small">
                  {turn.provider} · {(turn.latency_ms / 1000).toFixed(1)}s
                </span>
              </div>
            </li>
          );
        })}
      </ol>
      {turns.length === 0 && (
        <p className="muted center">
          {targetVoice ? `Speech output available for ${LANGUAGE_NAMES[target]}.` : `No ${LANGUAGE_NAMES[target]} voice installed: translations will be text only.`}
        </p>
      )}
    </div>
  );
}
