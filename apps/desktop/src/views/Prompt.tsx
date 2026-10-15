// The prompt: the only part of Vico that takes the keyboard. It shows what you said or
// type, asks before an action, and holds the one-time setup. No cards, no forms.
import { useEffect, useRef, useState } from "react";
import { api, errorMessage } from "../lib/api";
import type { Session, Intent } from "../lib/session";

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

/** One-time setup and the tiny settings: an access code and one switch. */
function Setup({ session, send }: { session: Session; send: (i: Intent) => void }) {
  const first = session.phase === "setup";
  const [gemini, setGemini] = useState("");
  const [groq, setGroq] = useState("");
  const [approval, setApproval] = useState(true);
  const [configured, setConfigured] = useState<Record<string, boolean>>({});
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    api.secrets().then(setConfigured).catch(() => undefined);
    api.settings().then((s) => setApproval(s.require_approval)).catch(() => undefined);
  }, []);

  const save = async () => {
    setSaving(true);
    setError(null);
    try {
      if (gemini.trim()) await api.saveSecret("gemini", gemini.trim());
      if (groq.trim()) await api.saveSecret("groq", groq.trim());
      const keys = await api.secrets();
      if (!keys.gemini && !keys.groq) throw new Error("Paste your Gemini access code to continue.");
      await api.updateSettings({ cloud_consent: true, onboarding_complete: true, require_approval: approval });
      send({ type: "configured" });
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setSaving(false);
    }
  };

  return (
    <form
      className="setup"
      onSubmit={(e) => {
        e.preventDefault();
        void save();
      }}
      data-testid="setup"
    >
      <p className="eyebrow">{first ? "Hello, I'm Vico" : "Vico"}</p>
      {first && (
        <p className="lead">
          Tell me what to do in English, Yorùbá, Hausa or Igbo, and I'll do it on this computer.
        </p>
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
          autoFocus
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
      <p className="fine">
        To understand you, your voice and requests go to Google Gemini (and Groq if you add it). Vico never pays,
        never types passwords, and always asks before deleting or sending.
      </p>
      {error && <p className="error-line" role="alert">{error}</p>}
      <div className="choices">
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
    if (["listening", "typing", "review", "question"].includes(phase)) input.current?.focus();
  }, [phase]);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        e.preventDefault();
        send(phase === "approval" ? { type: "reject" } : { type: "escape" });
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [phase, send]);

  if (phase === "setup" || phase === "settings") {
    return (
      <div className="prompt setup-mode" data-testid="prompt">
        <Setup session={session} send={send} />
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

  const placeholder =
    phase === "listening" ? "Listening…" : phase === "transcribing" ? "…" : phase === "question" ? "Your answer" : "Tell me what to do";
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
            if (phase === "listening") send({ type: "stop-listening" });
            else send({ type: "submit" });
          }
        }}
        data-testid="words"
      />
      {phase === "review" && session.reviewUntil && <div className="fuse" key={session.reviewUntil} />}
      <Hints>
        {phase === "listening" && (
          <>
            Speak, or just start typing · <Key>⏎</Key> when done · <Key>esc</Key> to close
          </>
        )}
        {phase === "transcribing" && <>Catching your words</>}
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
                <button className="link" onClick={() => send({ type: "listen" })}>
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
