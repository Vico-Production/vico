// The aura: a see-through, click-through layer over the screen where Vico's look lives.
// Nothing here darkens or covers your apps. It never takes the mouse, except while the cursor
// is over the look's handle (Peek's hands, the yo-yo's anchor, Possession's label) so you can
// drag it somewhere else.
import { useEffect, useRef, useState, type PointerEvent as ReactPointerEvent } from "react";
import { listen } from "../lib/bus";
import { ORB, bottomHome, peekHome, usableTarget, yoyoHome, yoyoLength } from "../lib/layout";
import { native } from "../lib/native";
import { moodFor, type Intent, type Phase, type Session } from "../lib/session";
import { CanvasAvatar, runnerHome, type World } from "./CanvasLooks";
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
  const [dodgeAt, setDodgeAt] = useState<{ x: number; y: number } | null>(null);
  const [noMagnifier, setNoMagnifier] = useState(false);
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
    const body = el.querySelector(".peek-figure .hd, .orb, .possession-pill, .canvas-handle")?.getBoundingClientRect();
    if (!body || drag) return;
    const speed = prev ? Math.hypot(p.x - prev.x, p.y - prev.y) / Math.max(1, p.t - prev.t) : 1;
    if (!overHandle && near(p, body, 60) && speed < 0.35) {
      leftAt.current = 0;
      if (!dodge) {
        setDodge(true);
        setDodgeAt({ x: p.x, y: p.y });
      }
    } else if (dodge && !near(p, body, 140)) {
      if (!leftAt.current) leftAt.current = p.t;
      if (p.t - leftAt.current > 1000) setDodge(false);
    }
  });

  // Dragging: listeners go on at once (a quick click must still end the drag), and a click
  // that doesn't move leaves the look where it is.
  const latest = useRef(session);
  latest.current = session;
  const grab = (e: ReactPointerEvent) => {
    e.preventDefault();
    (e.target as Element).setPointerCapture?.(e.pointerId);
    setDodge(false);
    const start = { x: e.clientX, y: e.clientY };
    setDrag(start);
    const move = (ev: PointerEvent) => setDrag({ x: ev.clientX, y: ev.clientY });
    const end = (ev: PointerEvent) => {
      window.removeEventListener("pointermove", move);
      window.removeEventListener("pointerup", end);
      window.removeEventListener("pointercancel", end);
      setDrag(null);
      interactive.current = false;
      void native.auraInteractive?.(false);
      if (Math.hypot(ev.clientX - start.x, ev.clientY - start.y) < 6) return; // just a click
      const current = latest.current;
      const spots = { ...current.spots };
      const t = usableTarget(current.target, screen);
      if (current.look === "possession") {
        spots.possession_label = t && ev.clientY > t.y + t.height / 2 ? 1 : 0;
      } else if (current.look === "runner") {
        spots.runner = t ? Math.max(0, Math.min(1, (ev.clientX - t.x) / t.width)) : 0.3;
      } else {
        spots[current.look] = Math.max(0, Math.min(1, ev.clientX / screen.width));
      }
      if (current.look === "yoyo") setSettle((n) => n + 1);
      send?.({ type: "spot", spots });
    };
    window.addEventListener("pointermove", move);
    window.addEventListener("pointerup", end);
    window.addEventListener("pointercancel", end);
  };
  // Moving out of the way means sliding aside, never vanishing: away from the cursor's side.
  const aside = (homeX: number) => {
    if (!dodge || !dodgeAt) return homeX;
    const shifted = homeX + (dodgeAt.x < homeX ? 140 : -140);
    return Math.max(70, Math.min(screen.width - 70, shifted));
  };

  const promptOwnsText = ["setup", "settings", "transcribing", "review", "typing", "question", "approval"].includes(phase)
    || (phase === "listening" && !session.followUp);
  const hasWords = !promptOwnsText && (Boolean(session.narration) || ["done", "error", "cooling"].includes(phase));
  const act = phase === "working" || phase === "thinking" ? session.act : null;

  let body: React.ReactNode = null;
  if (look === "peek") {
    const home = drag ? drag.x : aside(peekHome(screen, session.spots));
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
    const home = drag ? drag.x : aside(yoyoHome(screen, session.spots));
    const length = drag ? 20 : present ? yoyoLength(mood) : 0;
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
  } else if (look === "swarm" || look === "runner" || look === "lens") {
    const target = usableTarget(session.target, screen);
    const home = look === "runner"
      ? runnerHome({ target, height: screen.height }, drag ? drag.x : screen.width / 2,
        drag && target ? (drag.x - target.x) / target.width : session.spots.runner)
      : { ...bottomHome(look, screen, session.spots), ...(drag ? { x: drag.x } : {}) };
    const world: World = { width: screen.width, height: screen.height, home, target, act, mood, reaction,
      level: session.level, dodge: dodge ? dodgeAt : null };
    const above = look === "lens" ? 80 : look === "runner" ? 64 : 120;
    body = (
      <>
        <CanvasAvatar look={look} world={world} onGrab={grab} onMagnifier={(ok) => setNoMagnifier(!ok)} />
        {hasWords && present && !act?.rect && (
          <div className={`bubble below-none mood-${mood}`} style={{ left: home.x, bottom: screen.height - home.y + above }}>
            <Words session={session} withNarration />
          </div>
        )}
        {look === "lens" && noMagnifier && present && (
          <p className="lens-note" style={{ left: home.x + 80, top: home.y - 12 }}>
            This computer can't magnify the screen, so the Lens is clear glass.
          </p>
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
