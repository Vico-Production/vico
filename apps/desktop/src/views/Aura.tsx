// The aura: a see-through, click-through layer over the whole screen where Vico's look
// lives. Nothing here darkens or covers your apps, and it never takes the mouse or keyboard.
import { useEffect, useRef, useState } from "react";
import { PEEK_H, PEEK_W, YOYO_X_FROM_RIGHT, ORB, peekCenter, usableTarget, yoyoLength } from "../lib/layout";
import { PROMPT_PHASES, moodFor, type Phase, type Session } from "../lib/session";
import { PeekFigure, PossessionFrame, YoyoFigure } from "./Looks";

function useScreen() {
  const [screen, setScreen] = useState({ width: window.innerWidth, height: window.innerHeight });
  useEffect(() => {
    const resize = () => setScreen({ width: window.innerWidth, height: window.innerHeight });
    window.addEventListener("resize", resize);
    return () => window.removeEventListener("resize", resize);
  }, []);
  return screen;
}

function formatClock(seconds: number): string {
  const s = Math.max(0, Math.ceil(seconds));
  if (s >= 3600) return `${Math.floor(s / 3600)}h ${String(Math.floor((s % 3600) / 60)).padStart(2, "0")}m`;
  return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`;
}

/** Counts down while the free key rests. */
function Cooldown({ until }: { until: number }) {
  const [now, setNow] = useState(Date.now());
  const total = useRef(Math.max(1, (until - Date.now()) / 1000));
  useEffect(() => {
    const id = window.setInterval(() => setNow(Date.now()), 250);
    return () => window.clearInterval(id);
  }, []);
  const left = Math.max(0, (until - now) / 1000);
  return (
    <span className="cooldown" role="timer" aria-label={`Resuming in ${formatClock(left)}`} data-testid="cooldown"
      style={{ ["--left" as string]: (left / total.current).toFixed(3) }}>
      <i />
      {formatClock(left)}
    </span>
  );
}

/** What the look says while the prompt is not on screen: progress, results, problems. */
function Words({ session, withNarration }: { session: Session; withNarration: boolean }) {
  const { phase } = session;
  if (phase === "done" || phase === "error") {
    return (
      <div className={`result ${phase}`} key={`${phase}-${session.message}`} data-testid="result">
        {session.localized && <p className="echo">{session.localized}</p>}
        <p>{session.message}</p>
      </div>
    );
  }
  return (
    <>
      {phase === "cooling" && session.cooldownUntil && <Cooldown until={session.cooldownUntil} />}
      {withNarration && session.narration && (
        <p className="line" key={session.narration} data-testid="narration">
          {session.narration}
        </p>
      )}
    </>
  );
}

/** Short words for the Possession pill while the prompt holds the conversation. */
function pillText(phase: Phase, narration: string): string {
  switch (phase) {
    case "listening":
      return "listening";
    case "transcribing":
      return "catching your words";
    case "review":
      return "heard you";
    case "typing":
      return "type below";
    case "question":
      return "one question";
    case "approval":
      return "may I?";
    case "done":
      return "done";
    case "error":
      return "couldn't finish";
    default:
      return narration;
  }
}

export function Aura({ session }: { session: Session }) {
  const screen = useScreen();
  const { phase, look } = session;
  const mood = moodFor(phase);
  const promptOwnsText = PROMPT_PHASES.includes(phase);
  const hasWords = !promptOwnsText && (Boolean(session.narration) || ["done", "error", "cooling"].includes(phase));
  const present = mood !== "away";

  let body: React.ReactNode = null;
  if (look === "peek") {
    const center = peekCenter(mood, screen, session.target);
    body = (
      <>
        <div className="peek-at" style={{ left: center - PEEK_W / 2, ["--h" as string]: `${PEEK_H}px` }}>
          <PeekFigure mood={mood} level={session.level} width={PEEK_W} />
        </div>
        {hasWords && present && (
          <div className={`bubble below-none mood-${mood}`} style={{ left: center, bottom: PEEK_H + 16 }}>
            <Words session={session} withNarration />
          </div>
        )}
      </>
    );
  } else if (look === "yoyo") {
    const length = yoyoLength(mood);
    const x = screen.width - YOYO_X_FROM_RIGHT;
    body = (
      <>
        <div className="yoyo-at" style={{ left: x - ORB / 2 }}>
          <YoyoFigure mood={mood} length={length} size={ORB} />
        </div>
        {hasWords && present && (
          <div className={`bubble side mood-${mood}`} style={{ right: screen.width - x + ORB / 2 + 16, top: length }}>
            <Words session={session} withNarration />
          </div>
        )}
      </>
    );
  } else {
    const target = usableTarget(session.target, screen);
    const text = pillText(phase, session.narration);
    const showResult = ["done", "error", "cooling"].includes(phase);
    body = present ? (
      <>
        <PossessionFrame mood={mood} rect={target} text={text} level={session.level} />
        {showResult && (
          <div className={`bubble inside mood-${mood}`}
            style={target ? { left: target.x + target.width / 2, top: target.y + 46 } : { left: screen.width / 2, top: 64 }}>
            <Words session={session} withNarration={false} />
          </div>
        )}
      </>
    ) : null;
  }

  return (
    <div className={`aura phase-${phase} look-${look}`} data-testid="aura" aria-hidden={phase === "hidden"} role="status"
      aria-live="polite">
      {body}
    </div>
  );
}
