// The aura: a see-through, click-through layer over the screen where Vico's look lives.
// Nothing here darkens or covers your apps. It never takes the mouse, except while the cursor
// is over the look's handle (Peek's hands, the yo-yo's anchor, Possession's label) so you can
// drag it somewhere else.
import { useEffect, useRef, useState, type PointerEvent as ReactPointerEvent } from "react";
import { listen } from "../lib/bus";
import { ORB, peekHome, usableTarget, yoyoHome, yoyoLength } from "../lib/layout";
import { native } from "../lib/native";
import { moodFor, type Intent, type Phase, type Session } from "../lib/session";
import { PeekAvatar, PossessionAvatar, YoyoAvatar, faceFor, type Reaction } from "./Looks";

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
      key resting · back in {formatClock(left)}
    </span>
  );
}

/** What Vico says while the keyboard is yours: progress, results, problems, follow-ups. */
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
          {phase === "listening" && <i className="ear" style={{ ["--level" as string]: session.level.toFixed(3) }} />}
          {session.narration}
        </p>
      )}
    </>
  );
}

/** Short words for the Possession label while the prompt holds the conversation. */
function pillText(session: Session): string {
  switch (session.phase) {
    case "listening":
      return session.followUp ? "anything else? I'm listening" : "listening";
    case "transcribing":
      return "catching your words";
    case "review":
      return "got it";
    case "typing":
      return "type below";
    case "question":
      return "your turn";
    case "approval":
      return "your turn · ↵ yes · esc no";
    case "done":
      return session.reaction === "celebrate" ? "done" : session.message ?? "done";
    case "error":
      return "couldn't finish";
    case "staying":
      return "here if you need me";
    default:
      return session.narration;
  }
}

/** Reactions that last as long as their situation does. */
function lastingReaction(phase: Phase): Reaction | null {
  if (phase === "approval" || phase === "question") return "wait";
  if (phase === "cooling") return "cooling";
  if (phase === "staying") return "doze";
  return null;
}

type Point = { x: number; y: number; t: number };

/** The mouse, as seen by a click-through layer: from the Rust shell in the app, or the page. */
function useCursor(onMove: (p: Point) => void) {
  const handler = useRef(onMove);
  handler.current = onMove;
  useEffect(() => {
    const fromPage = (e: MouseEvent) => handler.current({ x: e.clientX, y: e.clientY, t: performance.now() });
    window.addEventListener("mousemove", fromPage);
    const stop = listen<{ x: number; y: number }>("vico://cursor", (p) => handler.current({ ...p, t: performance.now() }));
    return () => {
      window.removeEventListener("mousemove", fromPage);
      stop();
    };
  }, []);
}

const near = (p: Point, r: DOMRect, pad: number) =>
  p.x > r.left - pad && p.x < r.right + pad && p.y > r.top - pad && p.y < r.bottom + pad;

export function Aura({ session, send }: { session: Session; send?: (intent: Intent) => void }) {
  const screen = useScreen();
  const { phase, look } = session;
  const mood = moodFor(phase);
  const reaction = session.reaction ?? lastingReaction(phase);
  const face = faceFor(mood, reaction, session.level);
  const present = mood !== "away" || phase === "listening";
  const root = useRef<HTMLDivElement>(null);

  // Dodging and dragging use different parts: the body ducks away from a slowing cursor, the
  // handle stays put and is what you grab.
  const [dodge, setDodge] = useState(false);
  const [drag, setDrag] = useState<{ x: number; y: number } | null>(null);
  const [settle, setSettle] = useState(0);
  const last = useRef<Point | null>(null);
  const leftAt = useRef(0);
  const interactive = useRef(false);

  useCursor((p) => {
    const prev = last.current;
    last.current = p;
    const el = root.current;
    if (!el || !present) return;
    const handle = el.querySelector(".handle, .possession-pill")?.getBoundingClientRect();
    const overHandle = Boolean(handle && near(p, handle, 4));
    if (overHandle !== interactive.current && !drag) {
      interactive.current = overHandle;
      void native.auraInteractive?.(overHandle);
    }
    const body = el.querySelector(".peek-figure .hd, .orb, .possession-pill")?.getBoundingClientRect();
    if (!body || drag) return;
    const speed = prev ? Math.hypot(p.x - prev.x, p.y - prev.y) / Math.max(1, p.t - prev.t) : 1;
    if (!overHandle && near(p, body, 60) && speed < 0.35) {
      leftAt.current = 0;
      if (!dodge) setDodge(true);
    } else if (dodge && !near(p, body, 140)) {
      if (!leftAt.current) leftAt.current = p.t;
      if (p.t - leftAt.current > 1000) setDodge(false);
    }
  });

  const grab = (e: ReactPointerEvent) => {
    e.preventDefault();
    (e.target as Element).setPointerCapture?.(e.pointerId);
    setDodge(false);
    setDrag({ x: e.clientX, y: e.clientY });
  };
  useEffect(() => {
    if (!drag) return;
    const move = (e: PointerEvent) => setDrag({ x: e.clientX, y: e.clientY });
    const up = (e: PointerEvent) => {
      const spots = { ...session.spots };
      if (look === "possession") {
        const t = usableTarget(session.target, screen);
        spots.possession_label = t && e.clientY > t.y + t.height / 2 ? 1 : 0;
      } else {
        spots[look === "peek" ? "peek" : "yoyo"] = Math.max(0, Math.min(1, e.clientX / screen.width));
      }
      setDrag(null);
      if (look === "yoyo") setSettle((n) => n + 1);
      interactive.current = false;
      void native.auraInteractive?.(false);
      send?.({ type: "spot", spots });
    };
    window.addEventListener("pointermove", move);
    window.addEventListener("pointerup", up, { once: true });
    return () => {
      window.removeEventListener("pointermove", move);
      window.removeEventListener("pointerup", up);
    };
  }, [drag !== null]); // eslint-disable-line react-hooks/exhaustive-deps

  const promptOwnsText = ["setup", "settings", "transcribing", "review", "typing", "question", "approval"].includes(phase)
    || (phase === "listening" && !session.followUp);
  const hasWords = !promptOwnsText && (Boolean(session.narration) || ["done", "error", "cooling"].includes(phase));
  const act = phase === "working" || phase === "thinking" ? session.act : null;

  let body: React.ReactNode = null;
  if (look === "peek") {
    const home = drag ? drag.x : peekHome(screen, session.spots);
    body = (
      <>
        <PeekAvatar key={`peek-${session.reactionAt}`} face={face} reaction={reaction} act={act} dodge={dodge}
          grabbed={Boolean(drag)} onGrab={grab} homeX={home} screenHeight={screen.height} away={!present} />
        {hasWords && present && !act?.rect && (
          <div className={`bubble below-none mood-${mood}`} style={{ left: home, bottom: 100 }}>
            <Words session={session} withNarration />
          </div>
        )}
      </>
    );
  } else if (look === "yoyo") {
    const home = drag ? drag.x : yoyoHome(screen, session.spots);
    const length = drag ? 20 : dodge ? 6 : present ? yoyoLength(mood) : 0;
    const leftSide = home > screen.width / 2;
    body = (
      <>
        <YoyoAvatar key={`yoyo-${session.reactionAt}`} face={face} reaction={reaction} act={act} dodge={dodge}
          grabbed={Boolean(drag)} onGrab={grab} homeX={home} length={length} settle={settle} />
        {hasWords && present && !act?.rect && (
          <div className={`bubble ${leftSide ? "side" : "side-right"} mood-${mood}`}
            style={leftSide ? { right: screen.width - home + ORB / 2 + 16, top: length } : { left: home + ORB / 2 + 16, top: length }}>
            <Words session={session} withNarration />
          </div>
        )}
      </>
    );
  } else if (present) {
    const target = usableTarget(session.target, screen);
    const labelBottom = drag && target ? drag.y > target.y + target.height / 2 : (session.spots.possession_label ?? 0) >= 0.5;
    const showResult = ["done", "error", "cooling"].includes(phase) && session.reaction !== "celebrate";
    body = (
      <>
        <PossessionAvatar key={`possession-${session.reactionAt}`} face={face} reaction={reaction} act={act} dodge={dodge}
          grabbed={Boolean(drag)} onGrab={grab} mood={mood} rect={target} text={`Vico · ${pillText(session)}`}
          level={session.level} labelBottom={labelBottom} screenWidth={screen.width} />
        {showResult && (
          <div className={`bubble inside mood-${mood}`}
            style={target ? { left: target.x + target.width / 2, top: target.y + 46 } : { left: screen.width / 2, top: 64 }}>
            <Words session={session} withNarration={false} />
          </div>
        )}
      </>
    );
  }

  return (
    <div ref={root} className={`aura phase-${phase} look-${look}`} data-testid="aura" aria-hidden={phase === "hidden"}
      role="status" aria-live="polite">
      {body}
    </div>
  );
}
