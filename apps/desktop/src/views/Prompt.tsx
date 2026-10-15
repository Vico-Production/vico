// The prompt: the only part of Vico that takes the keyboard. It shows what you said or
// type, asks before an action, and holds the one-time setup. No cards, no forms.
import { useEffect, useRef, useState } from "react";
import { api, errorMessage } from "../lib/api";
import type { Look } from "../lib/layout";
import type { Session, Intent } from "../lib/session";
import { LookPicker } from "./Looks";

const HOLD_MS = 1200;

function Hints({ children }: { children: React.ReactNode }) {
  return <p className="hints">{children}</p>;
}

function Key({ children }: { children: React.ReactNode }) {
  return <kbd>{children}</kbd>;
}

/** Allow or stop. Risky steps (delete, commands, uploads, sends) need Enter held down. */
function Approval({ session, send }: { session: Session; send: (i: Intent) => void }) {
  const step = session.step!;
  const hold = step.outcome === "confirm_required";
  const [progress, setProgress] = useState(0);
  const holdStart = useRef<number | null>(null);
  const raf = useRef(0);

  useEffect(() => {
    const tickHold = () => {
      if (holdStart.current === null) return;
      const p = Math.min(1, (performance.now() - holdStart.current) / HOLD_MS);
      setProgress(p);
      if (p >= 1) {
        holdStart.current = null;
        send({ type: "approve", confirm: true });
        return;
      }
      raf.current = requestAnimationFrame(tickHold);
    };
    const down = (e: KeyboardEvent) => {
      if (e.key !== "Enter" || e.repeat) return;
      e.preventDefault();
      if (!hold) return send({ type: "approve", confirm: false });
      holdStart.current = performance.now();
      raf.current = requestAnimationFrame(tickHold);
    };
    const up = (e: KeyboardEvent) => {
      if (e.key !== "Enter" || !hold) return;
      holdStart.current = null;
      cancelAnimationFrame(raf.current);
      setProgress(0);
    };
    window.addEventListener("keydown", down);
    window.addEventListener("keyup", up);
    return () => {
      window.removeEventListener("keydown", down);
      window.removeEventListener("keyup", up);
      cancelAnimationFrame(raf.current);
    };
  }, [hold, send]);

  const startPointerHold = () => {
    if (!hold) return send({ type: "approve", confirm: false });
    holdStart.current = performance.now();
    const tickHold = () => {
      if (holdStart.current === null) return;
      const p = Math.min(1, (performance.now() - holdStart.current) / HOLD_MS);
      setProgress(p);
      if (p >= 1) {
        holdStart.current = null;
        send({ type: "approve", confirm: true });
        return;
      }
      raf.current = requestAnimationFrame(tickHold);
    };
    raf.current = requestAnimationFrame(tickHold);
  };
  const endPointerHold = () => {
    if (!hold) return;
    holdStart.current = null;
    cancelAnimationFrame(raf.current);
    setProgress(0);
  };

  return (
    <div className={`approval ${hold ? "hold" : ""}`} data-testid="approval">
      <p className="eyebrow">{hold ? "This one needs a careful yes" : "May I?"}</p>
      <p className="effect" data-testid="approval-effect">
        {step.effect}
      </p>
      {hold && <p className="why">{step.reason}</p>}
      <div className="choices">
        <button
          className="drop allow"
          style={{ ["--fill" as string]: progress.toFixed(3) }}
          onPointerDown={startPointerHold}
          onPointerUp={endPointerHold}
          onPointerLeave={endPointerHold}
          data-testid="allow"
        >
          <span>{hold ? "Hold to allow" : "Allow"}</span> <Key>⏎</Key>
        </button>
        <button className="drop stop" onClick={() => send({ type: "reject" })} data-testid="stop">
          <span>Stop</span> <Key>esc</Key>
        </button>
      </div>
    </div>
  );
}

/** First run (pick a look, then an access code) and the small settings panel. */
function Setup({ session, send }: { session: Session; send: (i: Intent) => void }) {
  const first = session.phase === "setup";
  const [step, setStep] = useState<"look" | "codes">(first ? "look" : "codes");
  const [look, setLook] = useState<Look | null>(first ? null : session.look);
  const [gemini, setGemini] = useState("");
  const [groq, setGroq] = useState("");
  const [approval, setApproval] = useState(true);
  const [wake, setWake] = useState(true);
  const [serverUrl, setServerUrl] = useState("");
  const [serverToken, setServerToken] = useState("");
  const [voice, setVoice] = useState(true);
  const [serverCheck, setServerCheck] = useState<string | null>(null);
  const [configured, setConfigured] = useState<Record<string, boolean>>({});
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [confirmReset, setConfirmReset] = useState(false);

  const startOver = async () => {
    if (!confirmReset) return setConfirmReset(true);
    try {
      await api.reset();
      send({ type: "reset" });
    } catch (err) {
      setError(errorMessage(err));
    }
  };

  useEffect(() => {
    api.secrets().then(setConfigured).catch(() => undefined);
    api
      .settings()
      .then((s) => {
        setApproval(s.require_approval);
        if (!first && s.look) setLook(s.look);
        setWake(s.wake_word);
        setServerUrl(s.speech_server_url ?? "");
        setVoice(s.voice_replies);
      })
      .catch(() => undefined);
  }, []);

  const checkServer = async () => {
    setServerCheck("Checking…");
    try {
      if (serverToken.trim()) await api.saveSecret("speech_server", serverToken.trim());
      await api.updateSettings({ speech_server_url: serverUrl.trim() || null });
      const h = await api.speechServerHealth();
      setServerCheck(`Connected · listening ${h.asr.ready ? "ready" : "off"} · voice ${h.voice.ready ? "ready" : "off"}`);
    } catch (err) {
      setServerCheck(errorMessage(err));
    }
  };

  const save = async () => {
    setSaving(true);
    setError(null);
    try {
      if (gemini.trim()) await api.saveSecret("gemini", gemini.trim());
      if (groq.trim()) await api.saveSecret("groq", groq.trim());
      const keys = await api.secrets();
      if (!keys.gemini && !keys.groq) throw new Error("Paste your Gemini access code to continue.");
      if (serverToken.trim()) await api.saveSecret("speech_server", serverToken.trim());
      const chosen = look ?? "peek";
      await api.updateSettings({
        look: chosen,
        cloud_consent: true,
        onboarding_complete: true,
        require_approval: approval,
        wake_word: wake,
        ...(first ? {} : { speech_server_url: serverUrl.trim() || null, voice_replies: voice }),
      });
      send({ type: "configured", look: chosen });
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setSaving(false);
    }
  };

  if (step === "look") {
    return (
      <form
        className="setup"
        onSubmit={(e) => {
          e.preventDefault();
          if (!look) return setError("Pick how I should appear. You can change it later in Settings.");
          setError(null);
          setStep("codes");
        }}
        data-testid="setup"
      >
        <p className="eyebrow">Hello, I'm Vico</p>
        <p className="lead">How should I appear on your screen? Each one plays a whole task: listening, thinking, then working.</p>
        <LookPicker value={look} onChange={(l) => { setLook(l); setError(null); }} />
        {error && <p className="error-line" role="alert">{error}</p>}
        <div className="choices">
          <button className="drop allow" type="submit" data-testid="look-continue">
            <span>Continue</span> <Key>⏎</Key>
          </button>
        </div>
      </form>
    );
  }

  return (
    <form
      className="setup"
      onSubmit={(e) => {
        e.preventDefault();
        void save();
      }}
      data-testid="setup"
    >
      <p className="eyebrow">{first ? "One last thing" : "Settings"}</p>
      {first ? (
        <p className="lead">
          Tell me what to do in English, Yorùbá, Hausa or Igbo, and I'll do it on this computer. I need one free code
          to understand you.
        </p>
      ) : (
        <>
          <p className="section">How I appear</p>
          <LookPicker value={look} onChange={setLook} />
          <p className="section">Access codes</p>
        </>
      )}
      <label className="line-field">
        <span>
          Your free Gemini access code {configured.gemini && <em>· saved</em>}
          <a href="https://aistudio.google.com/apikey" target="_blank" rel="noreferrer">
            get one free →
          </a>
        </span>
        <input
          type="password"
          autoComplete="off"
          autoFocus={first}
          value={gemini}
          placeholder={configured.gemini ? "•••••• (paste a new one to replace it)" : "Paste it here"}
          onChange={(e) => setGemini(e.target.value)}
          data-testid="gemini-code"
        />
      </label>
      <label className="line-field quiet">
        <span>
          Groq code, used if Gemini is busy · optional {configured.groq && <em>· saved</em>}
          <a href="https://console.groq.com/keys" target="_blank" rel="noreferrer">
            get one →
          </a>
        </span>
        <input type="password" autoComplete="off" value={groq} placeholder="Optional"
          onChange={(e) => setGroq(e.target.value)} />
      </label>
      <label className="switch">
        <input type="checkbox" checked={approval} onChange={(e) => setApproval(e.target.checked)} />
        <span className="track" aria-hidden="true" />
        <span>Ask me before acting</span>
      </label>
      <label className="switch">
        <input type="checkbox" checked={wake} onChange={(e) => setWake(e.target.checked)} data-testid="wake-word" />
        <span className="track" aria-hidden="true" />
        <span>Wake me when I say "Hey Vico" · heard only on this computer</span>
      </label>
      {!first && (
        <details className="server">
          <summary>Your speech server · optional</summary>
          <p className="fine">
            A free server you run yourself, with Meta Omnilingual ASR for Yorùbá, Hausa and Igbo speech and Nigerian
            voices for spoken answers. Setup guide: services/speech_server/README.md.
          </p>
          <label className="line-field quiet">
            <span>Address {configured.speech_server && <em>· token saved</em>}</span>
            <input value={serverUrl} placeholder="https://your-server" onChange={(e) => setServerUrl(e.target.value)} />
          </label>
          <label className="line-field quiet">
            <span>Token</span>
            <input
              type="password"
              autoComplete="off"
              value={serverToken}
              placeholder="Printed by the setup script"
              onChange={(e) => setServerToken(e.target.value)}
            />
          </label>
          <label className="switch">
            <input type="checkbox" checked={voice} onChange={(e) => setVoice(e.target.checked)} />
            <span className="track" aria-hidden="true" />
            <span>Answer me aloud</span>
          </label>
          <button type="button" className="link" onClick={() => void checkServer()} data-testid="test-server">
            test connection
          </button>
          {serverCheck && <p className="fine">{serverCheck}</p>}
        </details>
      )}
      <p className="fine">
        To understand you, your voice and requests go to Google Gemini (and Groq if you add it). Vico never pays,
        never types passwords, and always asks before deleting or sending.
      </p>
      {error && <p className="error-line" role="alert">{error}</p>}
      {!first && (configured.gemini || configured.groq) && (
        <button type="button" className="link danger" onClick={() => void startOver()} data-testid="start-over">
          {confirmReset ? "Click again to remove your codes and settings" : "Remove my codes and start over"}
        </button>
      )}
      <div className="choices">
        {first && (
          <button type="button" className="drop stop" onClick={() => setStep("look")}>
            <span>Back</span>
          </button>
        )}
        <button className="drop allow" type="submit" disabled={saving} data-testid="save-setup">
          <span>{first ? "Begin" : "Save"}</span> <Key>⏎</Key>
        </button>
      </div>
      <Hints>
        <Key>Win</Key> + <Key>Alt</Key> + <Key>V</Key> brings me back anytime · <Key>esc</Key> to close
      </Hints>
    </form>
  );
}

export function Prompt({ session, send }: { session: Session; send: (i: Intent) => void }) {
  const input = useRef<HTMLTextAreaElement>(null);
  const [value, setValue] = useState(session.text);
  const { phase } = session;

  // Follow what Vico heard; never overwrite the user's own typing.
  useEffect(() => {
    if (phase === "review" || phase === "listening" || phase === "question") setValue(session.text);
  }, [phase, session.text]);

  useEffect(() => {
    if (["typing", "review", "question"].includes(phase)) input.current?.focus();
  }, [phase]);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        e.preventDefault();
        send(phase === "approval" ? { type: "reject" } : { type: "escape" });
      } else if (phase === "listening" && e.key === "Enter") {
        e.preventDefault();
        send({ type: "stop-listening" });
      } else if (phase === "listening" && e.key.length === 1 && !e.ctrlKey && !e.metaKey && !e.altKey) {
        e.preventDefault();
        setValue(e.key);
        send({ type: "type", text: e.key });
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [phase, send]);

  if (phase === "setup" || phase === "settings") {
    return (
      <div className="prompt setup-mode" data-testid="prompt">
        <Setup key={phase} session={session} send={send} />
      </div>
    );
  }
  if (phase === "approval" && session.step) {
    return (
      <div className="prompt" data-testid="prompt">
        <Approval session={session} send={send} />
      </div>
    );
  }
  if (!["listening", "transcribing", "review", "typing", "question"].includes(phase)) {
    return <div className="prompt empty" data-testid="prompt" />;
  }

  // Voice first: listening is a voice view; the keyboard is one click (or keystroke) away.
  if (phase === "listening" || phase === "transcribing") {
    const bars = [0.55, 0.85, 1, 0.75, 0.5];
    return (
      <div className={`prompt voice ${phase}`} data-testid="prompt">
        <div className="voice-row">
          <div className="meter" aria-hidden="true">
            {bars.map((b, i) => (
              <i key={i} style={{ height: `${Math.round(6 + Math.min(1, session.level * 5) * 30 * b)}px` }} />
            ))}
          </div>
          <div className="voice-text">
            <p className="voice-title" data-testid="voice-title">
              {phase === "listening" ? "I'm listening…" : "Catching your words…"}
            </p>
            <p className="voice-sub">
              {phase === "listening" ? "Take your time. I'll wait until you finish." : "One moment"}
            </p>
          </div>
        </div>
        {session.micHint && phase === "listening" && (
          <p className="note" role="alert">
            {session.micHint}{" "}
            <button className="link" onClick={() => void api.openMicrophoneSettings().catch(() => undefined)}>
              microphone settings
            </button>
          </p>
        )}
        {phase === "listening" && session.narration && !session.micHint && <p className="note">{session.narration}</p>}
        <div className="voice-actions">
          <button className="drop" onClick={() => send({ type: "type-instead" })} data-testid="type-instead">
            <span>Type instead</span>
          </button>
          {phase === "listening" && (
            <button className="drop allow" onClick={() => send({ type: "stop-listening" })} data-testid="done-talking">
              <span>Done</span> <Key>⏎</Key>
            </button>
          )}
        </div>
      </div>
    );
  }

  const placeholder = phase === "question" ? "Your answer" : "Tell me what to do";
  return (
    <div className={`prompt ${phase}`} data-testid="prompt">
      {phase === "question" && <p className="ask">{session.question}</p>}
      <textarea
        ref={input}
        className="words"
        rows={1}
        value={value}
        placeholder={placeholder}
        spellCheck={false}
        aria-label="Tell Vico what to do"
        onChange={(e) => {
          setValue(e.target.value);
          send({ type: "type", text: e.target.value });
        }}
        onKeyDown={(e) => {
          if (e.key === "Enter" && !e.shiftKey) {
            e.preventDefault();
            send({ type: "submit" });
          }
        }}
        data-testid="words"
      />
      {phase === "review" && session.reviewUntil && <div className="fuse" key={session.reviewUntil} />}
      <Hints>
        {phase === "review" && (
          <>
            Going now · type to change it · <Key>esc</Key> to cancel
          </>
        )}
        {(phase === "typing" || phase === "question") && (
          <>
            <Key>⏎</Key> to go · <Key>esc</Key> to close
            {session.speech && phase === "typing" && (
              <>
                {" "}·{" "}
                <button className="link" onClick={() => send({ type: "listen" })} data-testid="talk-instead">
                  talk instead
                </button>
              </>
            )}
          </>
        )}
      </Hints>
      {session.narration && phase === "typing" && <p className="note">{session.narration}</p>}
    </div>
  );
}
