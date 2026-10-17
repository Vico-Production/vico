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

/** First run (pick a look or several to take turns, then an access code) and the settings panel,
 *  which opens only when the user asks Vico for its settings. */
function Setup({ session, send }: { session: Session; send: (i: Intent) => void }) {
  const first = session.phase === "setup";
  const [step, setStep] = useState<"look" | "codes">(first ? "look" : "codes");
  const [looks, setLooks] = useState<Look[]>(first ? [] : [session.look]);
  const [rotate, setRotate] = useState(false);
  const [gemini, setGemini] = useState("");
  const [groq, setGroq] = useState("");
  const [mistral, setMistral] = useState("");
  const [openrouter, setOpenrouter] = useState("");
  const [tinyfish, setTinyfish] = useState("");
  const [approval, setApproval] = useState(true);
  const [wake, setWake] = useState(true);
  const [serverUrl, setServerUrl] = useState("");
  const [serverToken, setServerToken] = useState("");
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
        if (!first) {
          setRotate(Boolean(s.rotate));
          setLooks(s.rotate && s.looks?.length ? s.looks : [s.look]);
        }
        setWake(s.wake_word);
        setServerUrl(s.speech_server_url ?? "");
      })
      .catch(() => undefined);
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  /** "One look" keeps a single pick; "Take turns" keeps every ticked look. */
  const chooseMode = (next: boolean) => {
    setRotate(next);
    setError(null);
    if (!next && looks.length > 1) setLooks(looks.slice(0, 1));
  };
  const lookProblem = (): string | null => {
    if (rotate && looks.length < 2) return "Tick at least two looks to take turns, or choose One look.";
    if (!looks.length) return "Pick how I should appear.";
    return null;
  };

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
    const problem = lookProblem();
    if (problem) return setError(problem);
    setSaving(true);
    setError(null);
    try {
      if (gemini.trim()) await api.saveSecret("gemini", gemini.trim());
      if (groq.trim()) await api.saveSecret("groq", groq.trim());
      if (mistral.trim()) await api.saveSecret("mistral", mistral.trim());
      if (openrouter.trim()) await api.saveSecret("openrouter", openrouter.trim());
      if (tinyfish.trim()) await api.saveSecret("tinyfish", tinyfish.trim());
      const keys = await api.secrets();
      if (!keys.gemini && !keys.groq) throw new Error("Paste your Gemini access code to continue.");
      if (serverToken.trim()) await api.saveSecret("speech_server", serverToken.trim());
      const current = looks[0];
      await api.updateSettings({
        look: current,
        looks,
        rotate: rotate && looks.length > 1,
        cloud_consent: true,
        onboarding_complete: true,
        require_approval: approval,
        wake_word: wake,
        ...(first ? {} : { speech_server_url: serverUrl.trim() || null }),
      });
      send({ type: "configured", look: current, first });
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setSaving(false);
    }
  };

  const modes = (
    <div className="modes" role="radiogroup" aria-label="One look or take turns">
      <button type="button" role="radio" aria-checked={!rotate} className={!rotate ? "on" : ""}
        onClick={() => chooseMode(false)} data-testid="mode-one">
        <strong>One look</strong>
        <span>The same one every time</span>
      </button>
      <button type="button" role="radio" aria-checked={rotate} className={rotate ? "on" : ""}
        onClick={() => chooseMode(true)} data-testid="mode-rotate">
        <strong>Take turns</strong>
        <span>Tick two or more; each time I come back I use the next one</span>
      </button>
    </div>
  );

  if (step === "look") {
    return (
      <form
        className="setup"
        onSubmit={(e) => {
          e.preventDefault();
          const problem = lookProblem();
          if (problem) return setError(problem);
          setError(null);
          setStep("codes");
        }}
        data-testid="setup"
      >
        <p className="eyebrow">Hello, I'm Vico</p>
        <p className="lead">How should I appear on your screen? Each one plays a whole task: listening, thinking, then working.</p>
        {modes}
        <LookPicker selected={looks} rotate={rotate} onChange={(l) => { setLooks(l); setError(null); }} />
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
          {modes}
          <LookPicker selected={looks} rotate={rotate} onChange={(l) => { setLooks(l); setError(null); }} />
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
      {!first && (
        <details className="server">
          <summary>More free backup codes · optional</summary>
          <p className="fine">
            Each one is used only when the ones above are busy or down, so Vico keeps understanding you.
          </p>
          <label className="line-field quiet">
            <span>
              Mistral code {configured.mistral && <em>· saved</em>}
              <a href="https://console.mistral.ai/api-keys" target="_blank" rel="noreferrer">get one →</a>
            </span>
            <input type="password" autoComplete="off" value={mistral} placeholder="Optional"
              onChange={(e) => setMistral(e.target.value)} />
          </label>
          <label className="line-field quiet">
            <span>
              OpenRouter code {configured.openrouter && <em>· saved</em>}
              <a href="https://openrouter.ai/settings/keys" target="_blank" rel="noreferrer">get one →</a>
            </span>
            <input type="password" autoComplete="off" value={openrouter} placeholder="Optional"
              onChange={(e) => setOpenrouter(e.target.value)} />
          </label>
          <label className="line-field quiet">
            <span>
              TinyFish code · Vico already searches the web without it; this makes searches faster and steadier
              {configured.tinyfish && <em> · saved</em>}
              <a href="https://agent.tinyfish.ai/api-keys" target="_blank" rel="noreferrer">get one →</a>
            </span>
            <input type="password" autoComplete="off" value={tinyfish} placeholder="Optional"
              onChange={(e) => setTinyfish(e.target.value)} data-testid="tinyfish-code" />
          </label>
        </details>
      )}
      <label className="switch">
        <input type="checkbox" checked={approval} onChange={(e) => setApproval(e.target.checked)}
          data-testid="ask-first" />
        <span className="track" aria-hidden="true" />
        <span>
          Ask me before acting
          <em className="switch-note">
            {approval ? " · Vico shows each step first" : " · off: Vico never asks, it just does it (deleted files go to the Recycle Bin)"}
          </em>
        </span>
      </label>
      <label className="switch">
        <input type="checkbox" checked={wake} onChange={(e) => setWake(e.target.checked)} data-testid="wake-word" />
        <span className="track" aria-hidden="true" />
        <span>Come when I say "Vico" · heard only on this computer</span>
      </label>
      {!first && (
        <details className="server">
          <summary>Your speech server · optional</summary>
          <p className="fine">
            A free server you run yourself, with Meta Omnilingual ASR for Yorùbá, Hausa and Igbo speech and YarnGPT
            Nigerian voices (the only free way for me to speak Yorùbá). Setup guide: services/speech_server/README.md.
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
          <button type="button" className="link" onClick={() => void checkServer()} data-testid="test-server">
            test connection
          </button>
          {serverCheck && <p className="fine">{serverCheck}</p>}
        </details>
      )}
      <p className="fine">
        To understand you, your voice and requests go to Google Gemini (and Groq if you add it). Vico never pays,
        never types passwords, and always asks before deleting or sending. Say "Vico, talk to me" to hear my answers
        aloud, or "Vico, just text" to stop.
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
    </form>
  );
}

/** The last screen of setup: only this sentence, until the user presses a key or talks to Vico. */
function Welcome() {
  return (
    <div className="prompt welcome" data-testid="welcome">
      <p className="welcome-text">
        If you want to come back to these settings, ask Vico to <strong>OPEN ITS SETTINGS</strong> — by voice or by
        typing.
      </p>
    </div>
  );
}

export function Prompt({ session, send }: { session: Session; send: (i: Intent) => void }) {
  const input = useRef<HTMLTextAreaElement>(null);
  const [value, setValue] = useState(session.text);
  const valueRef = useRef(value);
  valueRef.current = value;
  const talking = useRef(false); // Space is down for talking
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
      if (phase === "welcome") {
        // Enter or Esc closes the last setup card; typing starts talking to Vico.
        if (e.key === "Enter" || e.key === "Escape") {
          e.preventDefault();
          send({ type: "escape" });
        } else if (e.key.length === 1 && !e.ctrlKey && !e.metaKey && !e.altKey) {
          e.preventDefault();
          setValue(e.key);
          send({ type: "type", text: e.key });
        }
        return;
      }
      // Hold Space to talk (when there is nothing typed yet); letting go sends it.
      const empty = valueRef.current.trim() === "";
      if (e.code === "Space" && (phase === "listening" || phase === "answer" || ((phase === "typing" || phase === "question") && empty))) {
        e.preventDefault();
        if (!e.repeat && !talking.current) {
          talking.current = true;
          send({ type: "hold-talk" });
        }
        return;
      }
      if (e.key === "Escape") {
        e.preventDefault();
        send(phase === "approval" ? { type: "reject" } : { type: "escape" });
      } else if (phase === "listening" && e.key === "Enter") {
        e.preventDefault();
        send({ type: "stop-listening" });
      } else if ((phase === "listening" || phase === "answer") && e.key.length === 1 && !e.ctrlKey && !e.metaKey && !e.altKey) {
        e.preventDefault();
        setValue(e.key);
        send({ type: "type", text: e.key });
      }
    };
    const onKeyUp = (e: KeyboardEvent) => {
      if (e.code === "Space" && talking.current) {
        e.preventDefault();
        talking.current = false;
        send({ type: "release-talk" });
      }
    };
    // Letting go anywhere counts (the window can lose focus while Space is down).
    const onBlur = () => {
      if (talking.current) {
        talking.current = false;
        send({ type: "release-talk" });
      }
    };
    window.addEventListener("keydown", onKey);
    window.addEventListener("keyup", onKeyUp);
    window.addEventListener("blur", onBlur);
    return () => {
      window.removeEventListener("keydown", onKey);
      window.removeEventListener("keyup", onKeyUp);
      window.removeEventListener("blur", onBlur);
    };
  }, [phase, send]);

  if (phase === "welcome") return <Welcome />;
  if (phase === "answer") {
    return (
      <div className="prompt answer" data-testid="prompt">
        <div className="window-buttons">
          <button type="button" aria-label="Close" title="Close" onClick={() => send({ type: "escape" })}
            data-testid="close-answer">×</button>
        </div>
        <div className="answer-text" data-testid="answer" tabIndex={0}>
          {session.localized && <p className="echo">{session.localized}</p>}
          {(session.message ?? "").split("\n").map((line, i) => <p key={i}>{line}</p>)}
        </div>
        <Hints>
          <Key>esc</Key> to close{session.speech && <> · hold <Key>Space</Key> to ask more</>} · or just type
        </Hints>
      </div>
    );
  }
  if (phase === "setup" || phase === "settings") {
    // Folded away it keeps everything typed so far: open it again to carry on.
    return (
      <div className={`prompt setup-mode ${session.minimized ? "folded" : ""}`} data-testid="prompt">
        {session.minimized && (
          <button className="setup-pill" onClick={() => send({ type: "minimize", on: false })} data-testid="unfold">
            <span className="dot" /> {phase === "setup" ? "Finish setting up Vico" : "Vico settings"} · open
          </button>
        )}
        <div className="setup-frame" hidden={session.minimized}>
          <div className="window-buttons">
            <button type="button" aria-label="Minimize" title="Minimize (keeps what you typed)"
              onClick={() => send({ type: "minimize", on: true })} data-testid="minimize">–</button>
            <button type="button" aria-label="Close" title="Close" onClick={() => send({ type: "escape" })}
              data-testid="close-setup">×</button>
          </div>
          <Setup key={phase} session={session} send={send} />
        </div>
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
              {phase === "transcribing" ? "Catching your words…" : session.recording ? "I'm listening…"
                : "Hold Space and talk"}
            </p>
            <p className="voice-sub">
              {phase === "transcribing" ? "One moment"
                : session.recording ? "Take your time. Let go of Space (or press Enter) when you're done."
                  : "Let go when you're done. Or just start typing."}
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
        {phase === "listening" && session.question && <p className="ask">{session.question}</p>}
        <div className="voice-actions">
          <button className="drop" onClick={() => send({ type: "type-instead" })} data-testid="type-instead">
            <span>Type instead</span>
          </button>
          {phase === "listening" && session.recording && (
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
            {session.speech && (
              <>
                {" "}· hold <Key>Space</Key> to {phase === "question" ? "answer by voice" : "talk"}
              </>
            )}
          </>
        )}
      </Hints>
      {session.narration && phase === "typing" && <p className="note">{session.narration}</p>}
    </div>
  );
}
