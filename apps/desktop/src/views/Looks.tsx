// Vico's three looks. Each is drawn from the same moods and reactions, so the full-screen
// avatar and the small previews in setup always match. While a task runs the avatar acts out
// each real step at the real spot on screen (see lib/acting.ts).
import { useEffect, useRef, useState, type PointerEvent as ReactPointerEvent, type ReactNode } from "react";
import { actPoint, type Act, type Motion } from "../lib/acting";
import { ORB, PEEK_H, PEEK_W, type Look, type Mood, type Rect } from "../lib/layout";

/** Transient and lasting reactions, each tied to a real event (see session.ts). */
export type Reaction =
  | "arrive"
  | "gotit"
  | "wait"
  | "stay"
  | "bye"
  | "celebrate"
  | "shrug"
  | "refuse"
  | "move"
  | "huh"
  | "doze"
  | "cooling"
  | "greet";

export interface Face {
  mouth: "o" | "smile" | "flat" | "frown";
  eyes: "open" | "happy" | "half";
  gaze: "ahead" | "think" | "work" | "up" | "down";
  open: number; // 0..1, how wide the "o" is (the voice level while listening)
}

export function faceFor(mood: Mood, reaction: Reaction | null, level = 0): Face {
  const open = Math.min(1, level * 4);
  switch (reaction) {
    case "celebrate":
      return { mouth: "smile", eyes: "happy", gaze: "ahead", open };
    case "gotit":
    case "stay":
    case "greet":
    case "move":
    case "bye":
      return { mouth: "smile", eyes: "open", gaze: "ahead", open };
    case "wait":
      return { mouth: "smile", eyes: "open", gaze: "up", open };
    case "shrug":
    case "huh":
      return { mouth: "flat", eyes: "open", gaze: "down", open };
    case "refuse":
      return { mouth: "frown", eyes: "open", gaze: "ahead", open };
    case "doze":
    case "cooling":
      return { mouth: "flat", eyes: "half", gaze: "ahead", open };
    case "arrive":
      return { mouth: "o", eyes: "open", gaze: "ahead", open: 0.5 };
  }
  switch (mood) {
    case "listen":
      return { mouth: "o", eyes: "open", gaze: "ahead", open };
    case "think":
      return { mouth: "flat", eyes: "open", gaze: "think", open };
    case "work":
      return { mouth: "flat", eyes: "open", gaze: "work", open };
    case "ask":
      return { mouth: "smile", eyes: "open", gaze: "up", open };
    case "done":
      return { mouth: "smile", eyes: "happy", gaze: "ahead", open };
    case "sad":
      return { mouth: "frown", eyes: "open", gaze: "down", open };
    default:
      return { mouth: "smile", eyes: "open", gaze: "ahead", open };
  }
}

const PIN = "M15 4.5l-4 4-4 1.5-1.5 1.5 7 7 1.5-1.5 1.5-4 4-4M9 15l-4.5 4.5M14.5 4l5.5 5.5";

/** A little creature that holds the bottom edge of the screen and peeks over it. */
export function PeekFigure({ face, width = PEEK_W }: { face: Face; width?: number }) {
  return (
    <svg className={`peek-figure gaze-${face.gaze}`} width={width} height={width * 0.82} viewBox="0 0 80 66"
      style={{ overflow: "visible" }} aria-hidden="true">
      <g className="hd">
        <rect x="10" y="4" width="60" height="64" rx="28" fill="#1D9E75" />
        {face.eyes === "happy" ? (
          <path d="M23 29 Q30 21 37 29 M43 29 Q50 21 57 29" stroke="#04342C" strokeWidth="3" fill="none" strokeLinecap="round" />
        ) : (
          <>
            <circle cx="30" cy="27" r="9" fill="#fff" />
            <circle cx="50" cy="27" r="9" fill="#fff" />
            <circle className="pu" cx="30" cy="28" r="4" fill="#04342C" />
            <circle className="pu" cx="50" cy="28" r="4" fill="#04342C" />
            {face.eyes === "half" && <rect x="18" y="16" width="44" height="12" fill="#1D9E75" />}
          </>
        )}
        {face.mouth === "o" && <ellipse cx="40" cy="46" rx="4" ry={3 + face.open * 4} fill="#04342C" />}
        {face.mouth === "smile" && (
          <path d="M32 44 Q40 52 48 44" stroke="#04342C" strokeWidth="3" fill="none" strokeLinecap="round" />
        )}
        {face.mouth === "flat" && <path d="M34 47 H46" stroke="#04342C" strokeWidth="3" strokeLinecap="round" />}
        {face.mouth === "frown" && (
          <path d="M33 49 Q40 43 47 49" stroke="#04342C" strokeWidth="3" fill="none" strokeLinecap="round" />
        )}
      </g>
      <ellipse className="wv" cx="78" cy="30" rx="6" ry="9" fill="#5DCAA5" />
      <ellipse className="hl" cx="9" cy="61" rx="9" ry="6" fill="#5DCAA5" />
      <ellipse className="hr" cx="71" cy="61" rx="9" ry="6" fill="#5DCAA5" />
    </svg>
  );
}

/** The yo-yo's orb (the thread and anchor belong to the avatar). */
export function YoyoOrb({ face, size = ORB }: { face: Face; size?: number }) {
  return (
    <svg className={`orb gaze-${face.gaze}`} width={size} height={size} viewBox="0 0 46 46" aria-hidden="true">
      <circle cx="23" cy="23" r="21" fill="#1D9E75" />
      <path d="M3 23 H43" stroke="#0F6E56" strokeWidth="2" />
      {face.eyes === "happy" ? (
        <path d="M11 17 Q16 11 21 17 M25 17 Q30 11 35 17" stroke="#04342C" strokeWidth="2.4" fill="none" strokeLinecap="round" />
      ) : (
        <>
          <circle cx="16" cy="15" r="6" fill="#fff" />
          <circle cx="30" cy="15" r="6" fill="#fff" />
          <circle className="pu" cx="16" cy="16" r="3" fill="#04342C" />
          <circle className="pu" cx="30" cy="16" r="3" fill="#04342C" />
          {face.eyes === "half" && <rect x="9" y="8" width="28" height="8" fill="#1D9E75" />}
        </>
      )}
      {face.mouth === "o" && <ellipse cx="23" cy="32" rx="3" ry={2.5 + face.open * 3} fill="#04342C" />}
      {face.mouth === "smile" && (
        <path d="M17 31 Q23 37 29 31" stroke="#04342C" strokeWidth="2.4" fill="none" strokeLinecap="round" />
      )}
      {face.mouth === "flat" && <path d="M18 33 H28" stroke="#04342C" strokeWidth="2.4" strokeLinecap="round" />}
      {face.mouth === "frown" && (
        <path d="M17 35 Q23 30 29 35" stroke="#04342C" strokeWidth="2.4" fill="none" strokeLinecap="round" />
      )}
    </svg>
  );
}

/** Small symbolic motions for steps with no place on screen (files, commands, waiting). */
export function Prop({ motion }: { motion: Motion }) {
  return (
    <svg className={`prop prop-${motion}`} width="40" height="40" viewBox="0 0 40 40" aria-hidden="true">
      {(motion === "read" || motion === "scroll") && (
        <g>
          <rect x="7" y="4" width="26" height="32" rx="3" fill="#E1F5EE" />
          <g className="prop-lines" stroke="#5F5E5A" strokeWidth="2.4" strokeLinecap="round">
            <path d="M12 12 H28 M12 18 H25 M12 24 H28 M12 30 H22 M12 36 H27 M12 42 H24" />
          </g>
        </g>
      )}
      {(motion === "terminal" || motion === "type" || motion === "navigate") && (
        <g>
          <rect x="3" y="12" width="34" height="18" rx="3" fill="#2C2C2A" />
          {[0, 1, 2, 3, 4].map((i) => (
            <rect key={i} className={`key k${i}`} x={6 + i * 6.2} y="16" width="4.6" height="4.6" rx="1" fill="#9FE1CB" />
          ))}
          <rect x="10" y="23" width="20" height="4" rx="1" fill="#5DCAA5" />
        </g>
      )}
      {(motion === "wait" || motion === "open") && (
        <circle className="spinner" cx="20" cy="20" r="11" fill="none" stroke="#5DCAA5" strokeWidth="4" strokeDasharray="45 30"
          strokeLinecap="round" />
      )}
      {motion === "bin" && (
        <g>
          <path d="M11 22 H29 L27 37 H13 Z" fill="#888780" />
          <rect x="9" y="19" width="22" height="3" rx="1" fill="#5F5E5A" />
          <rect className="doc" x="15" y="2" width="10" height="13" rx="1.5" fill="#378ADD" />
        </g>
      )}
      {motion === "pop" && <path className="folder" d="M6 13 H16 L19 16 H34 V33 H6 Z" fill="#FAC775" />}
      {motion === "carry" && (
        <g>
          <path d="M24 16 H30 L32 18 H38 V30 H24 Z" fill="#FAC775" opacity="0.8" />
          <rect className="doc carry" x="2" y="14" width="10" height="13" rx="1.5" fill="#378ADD" />
        </g>
      )}
      {motion === "tap" && <circle className="ripple" cx="20" cy="20" r="8" fill="none" stroke="#5DCAA5" strokeWidth="3" />}
    </svg>
  );
}

/** Cancel the avatar's own travel animations, never the CSS ones its reactions use. */
function cancelTravel(el: Element | null) {
  if (!el?.getAnimations) return;
  for (const a of el.getAnimations()) {
    const css = typeof CSSAnimation !== "undefined" && a instanceof CSSAnimation;
    const transition = typeof CSSTransition !== "undefined" && a instanceof CSSTransition;
    if (!css && !transition) a.cancel();
  }
}

function squash(el: Element | null, frames: Keyframe[]) {
  el?.animate?.(frames, { duration: 220, easing: "ease-out" });
}

const TRAVEL_MS = 380; // within the 300-450 ms budget; a step never waits for it

interface AvatarProps {
  face: Face;
  reaction: Reaction | null;
  act: Act | null;
  dodge: boolean;
  grabbed: boolean;
  onGrab: (e: ReactPointerEvent) => void;
}

export function PeekAvatar({ face, reaction, act, dodge, grabbed, onGrab, homeX, screenHeight, away }:
  AvatarProps & { homeX: number; screenHeight: number; away: boolean }) {
  const root = useRef<HTMLDivElement>(null);
  const at = useRef<{ x: number; y: number } | null>(null);
  const point = act ? actPoint(act) : null;
  const key = point ? `${act?.id}:${Math.round(point.x)},${Math.round(point.y)}` : "home";

  useEffect(() => {
    const el = root.current;
    if (!el) return;
    const rest = { x: homeX, y: screenHeight - PEEK_H / 2 };
    const tf = (p: { x: number; y: number } | null) =>
      p ? `translate(${p.x - rest.x}px, ${p.y - rest.y - 10}px) scale(0.55)` : "translate(0px, 0px) scale(1)";
    const from = at.current;
    at.current = point;
    if (!from && !point) return;
    const f = from ?? rest;
    const t = point ?? rest;
    const mid = `translate(${(f.x + t.x) / 2 - rest.x}px, ${Math.min(f.y, t.y) - 70 - rest.y}px) scale(0.7)`;
    cancelTravel(el);
    const anim = el.animate?.([{ transform: tf(from) }, { transform: mid }, { transform: tf(point) }],
      { duration: TRAVEL_MS, easing: "cubic-bezier(.3,.7,.3,1)", fill: "forwards" });
    void anim?.finished.then(() => {
      if (!point) cancelTravel(el); // back home: hand the position back to the layout
      else if (act?.motion === "tap" || act?.motion === "open") {
        squash(el.querySelector(".hd"), [{ transform: "none" }, { transform: "scaleY(.6) translateY(6px)" }, { transform: "none" }]);
      }
    }).catch(() => undefined);
  }, [key, homeX, screenHeight]); // eslint-disable-line react-hooks/exhaustive-deps

  const symbolic = act && !point;
  return (
    <div ref={root} className={`peek-at avatar ${away ? "away" : ""} ${dodge ? "dodge" : ""} ${grabbed ? "grabbed" : ""}
      ${act?.running && act.motion === "type" ? "typing" : ""}`} data-r={reaction ?? ""}
      style={{ left: homeX - PEEK_W / 2 }}>
      <PeekFigure face={face} />
      {symbolic && <div className="prop-at peek-prop"><Prop motion={act.motion} /></div>}
      {reaction === "stay" && <svg className="pin-badge" viewBox="0 0 24 24" aria-hidden="true"><path d={PIN} /></svg>}
      {reaction === "doze" && <span className="zz">z z z</span>}
      {reaction === "huh" && <span className="q">?</span>}
      <div className="handle peek-handle" onPointerDown={onGrab} data-testid="avatar-handle" />
    </div>
  );
}

export function YoyoAvatar({ face, reaction, act, dodge, grabbed, onGrab, homeX, length, settle }:
  AvatarProps & { homeX: number; length: number; settle: number }) {
  const root = useRef<HTMLDivElement>(null);
  const thread = useRef<HTMLDivElement>(null);
  const at = useRef<{ x: number; y: number } | null>(null);
  const point = act ? actPoint(act) : null;
  const key = point ? `${act?.id}:${Math.round(point.x)},${Math.round(point.y)}` : "home";

  useEffect(() => {
    const el = root.current;
    const string = thread.current;
    if (!el || !string) return;
    const rest = { x: homeX, y: length + ORB / 2 };
    const from = at.current;
    at.current = point;
    if (!from && !point) return;
    const f = from ?? rest;
    const t = point ?? rest;
    let live = true;
    cancelTravel(el);
    cancelTravel(string);
    const run = (node: Element, frames: Keyframe[], ms: number, easing = "cubic-bezier(.3,.7,.3,1)") =>
      node.animate?.(frames, { duration: ms, easing, fill: "forwards" })?.finished ?? Promise.resolve();
    void (async () => {
      // pull the string up, slide the anchor along the top edge, drop onto the target
      await run(string, [{ height: `${Math.max(6, f.y - ORB / 2)}px` }, { height: "12px" }], 120);
      if (!live) return;
      await run(el, [{ transform: `translateX(${f.x - homeX}px)` }, { transform: `translateX(${t.x - homeX}px)` }], 150);
      if (!live) return;
      await run(string, [{ height: "12px" }, { height: `${Math.max(6, t.y - ORB / 2)}px` }], 130, "cubic-bezier(.3,1.5,.5,1)");
      if (!live) return;
      if (!point) {
        cancelTravel(el);
        cancelTravel(string);
      } else if (act?.motion === "tap" || act?.motion === "open") {
        squash(el.querySelector(".orb"), [{ transform: "none" }, { transform: "scale(1.15,.8) translateY(5px)" }, { transform: "none" }]);
      }
    })().catch(() => undefined);
    return () => {
      live = false;
    };
  }, [key, homeX, length]); // eslint-disable-line react-hooks/exhaustive-deps

  const symbolic = act && !point;
  return (
    <div ref={root} className={`yoyo-at avatar ${dodge ? "dodge" : ""} ${grabbed ? "grabbed" : ""}
      ${act?.running && act.motion === "type" ? "typing" : ""}`} data-r={reaction ?? ""}
      style={{ left: homeX - ORB / 2 }}>
      <div className="handle anchor" onPointerDown={onGrab} data-testid="avatar-handle" />
      <div className="yyin" key={settle} data-settle={settle ? "1" : ""}>
        <div ref={thread} className="thread" style={{ height: length }}>
          {reaction === "stay" && <svg className="pin-badge" viewBox="0 0 24 24" aria-hidden="true"><path d={PIN} /></svg>}
        </div>
        <YoyoOrb face={face} />
      </div>
      {symbolic && <div className="prop-at yoyo-prop" style={{ top: length }}><Prop motion={act.motion} /></div>}
      {reaction === "doze" && <span className="zz" style={{ top: length }}>z z z</span>}
      {reaction === "huh" && <span className="q" style={{ top: length }}>?</span>}
    </div>
  );
}

/** Possession: no body. Vico lights up the window it is using, talks on its edge, and a ghost
 *  cursor comes out of its label to act on the real spot. */
export function PossessionAvatar({ face, reaction, act, dodge, grabbed, onGrab, mood, rect, text, level, labelBottom,
  screenWidth }: AvatarProps & { mood: Mood; rect: Rect | null; text: ReactNode; level: number; labelBottom: boolean;
    screenWidth: number }) {
  void face;
  const ghost = useRef<HTMLDivElement>(null);
  const at = useRef<{ x: number; y: number } | null>(null);
  const point = act ? actPoint(act) : null;
  const key = point ? `${act?.id}:${Math.round(point.x)},${Math.round(point.y)}` : "home";
  const pill = rect
    ? { x: rect.x + 24, y: labelBottom ? rect.y + rect.height : rect.y }
    : { x: screenWidth / 2, y: 18 };

  useEffect(() => {
    const el = ghost.current;
    if (!el) return;
    const from = at.current ?? pill;
    at.current = point;
    if (!point && from === pill) return;
    const to = point ?? pill;
    cancelTravel(el);
    const anim = el.animate?.([
      { transform: `translate(${from.x}px, ${from.y}px)`, opacity: 1 },
      { transform: `translate(${to.x}px, ${to.y}px)`, opacity: point ? 1 : 0 },
    ], { duration: TRAVEL_MS - 20, easing: "cubic-bezier(.3,.7,.3,1)", fill: "forwards" });
    void anim?.finished.then(() => {
      if (point && (act?.motion === "tap" || act?.motion === "open" || act?.motion === "type")) {
        el.querySelector(".ring")?.animate?.([{ opacity: 1, transform: "scale(.4)" }, { opacity: 0, transform: "scale(1.6)" }],
          { duration: 320 });
      }
    }).catch(() => undefined);
  }, [key, pill.x, pill.y]); // eslint-disable-line react-hooks/exhaustive-deps

  const pillNode = (
    <div className={`possession-pill ${rect ? "" : "floating"} ${labelBottom ? "bottom" : ""} ${rect && rect.y < 24 ? "inside" : ""}
      ${dodge ? "dodged" : ""}`} data-testid="narration" onPointerDown={onGrab}>
      <i className="dot" />
      <span>{text}</span>
      {reaction === "stay" && <svg className="pin-inline" viewBox="0 0 24 24" aria-hidden="true"><path d={PIN} /></svg>}
    </div>
  );
  return (
    <>
      {rect ? (
        <div className={`possession avatar mood-${mood} ${grabbed ? "grabbed" : ""}`} data-r={reaction ?? ""}
          style={{ left: rect.x, top: rect.y, width: rect.width, height: rect.height, ["--level" as string]: level.toFixed(3) }}>
          <svg className="edge" width={rect.width} height={rect.height} aria-hidden="true">
            <rect x="1.5" y="1.5" width={Math.max(0, rect.width - 3)} height={Math.max(0, rect.height - 3)} rx="9" className="edge-base" />
            <rect x="1.5" y="1.5" width={Math.max(0, rect.width - 3)} height={Math.max(0, rect.height - 3)} rx="9" className="edge-run"
              pathLength="100" />
          </svg>
          {pillNode}
        </div>
      ) : (
        <div className={`possession-free avatar mood-${mood}`} data-r={reaction ?? ""}>{pillNode}</div>
      )}
      <div ref={ghost} className="ghost" aria-hidden="true">
        <svg width="16" height="20" viewBox="0 0 16 20"><path d="M1 1 L1 16 L5 12 L8 19 L11 18 L8 11 L14 11 Z" fill="#1D9E75"
          stroke="#04342C" strokeWidth="1" /></svg>
        <i className="ring" />
      </div>
      {act && !point && (
        <div className="prop-at possession-prop" style={{ left: pill.x + 150, top: pill.y - 20 }}><Prop motion={act.motion} /></div>
      )}
    </>
  );
}

// --- previews in setup ------------------------------------------------------------------

const CYCLE: { mood: Mood; reaction: Reaction | null; label: string; ms: number }[] = [
  { mood: "listen", reaction: "arrive", label: "Listening", ms: 1800 },
  { mood: "think", reaction: "gotit", label: "Got it", ms: 1300 },
  { mood: "work", reaction: null, label: "Working", ms: 2400 },
  { mood: "done", reaction: "celebrate", label: "Done", ms: 1700 },
  { mood: "away", reaction: null, label: "", ms: 700 },
];
const PREVIEW_TEXT: Record<Mood, string> = {
  listen: "open my browser…",
  think: "got it",
  work: "opening Edge",
  ask: "may I?",
  done: "done",
  sad: "",
  away: "",
};

/** A small screen that plays one look through a whole task, over and over. */
export function LookPreview({ look }: { look: Look }) {
  const [i, setI] = useState(0);
  useEffect(() => {
    const id = window.setTimeout(() => setI((n) => (n + 1) % CYCLE.length), CYCLE[i].ms);
    return () => window.clearTimeout(id);
  }, [i]);
  const { mood, reaction, label } = CYCLE[i];
  const face = faceFor(mood, reaction);
  const text = PREVIEW_TEXT[mood];
  const target: Rect = { x: 92, y: 22, width: 118, height: 82 };
  const visible = mood !== "away";
  return (
    <div className={`mini mood-${mood}`} aria-hidden="true">
      <div className="mini-screen">
        <div className="mini-win a" />
        <div className="mini-win b" style={{ left: target.x, top: target.y, width: target.width, height: target.height }} />
        {look === "peek" && (
          <>
            <div className={`mini-peek ${visible ? "" : "away"}`} data-r={reaction ?? ""}
              style={{ left: (mood === "work" ? 151 : 107) - 22, transform: mood === "work" ? "translateY(-62px) scale(.7)" : undefined }}>
              <PeekFigure face={face} width={44} />
            </div>
            {visible && mood !== "work" && (
              <div className="mini-bubble centered" style={{ left: 107, bottom: 42 }}>{text}</div>
            )}
          </>
        )}
        {look === "yoyo" && (
          <>
            <div className="mini-yoyo" data-r={reaction ?? ""} style={{ right: mood === "work" ? 48 : 18 }}>
              <div className="thread" style={{ height: mood === "work" ? 44 : visible ? 46 : 0 }} />
              <div style={{ opacity: visible ? 1 : 0 }}><YoyoOrb face={face} size={28} /></div>
            </div>
            {visible && mood !== "work" && <div className="mini-bubble" style={{ right: 52, top: 50 }}>{text}</div>}
          </>
        )}
        {look === "possession" && visible && (
          <div className={`mini-possess mood-${mood}`} style={{ left: mood === "listen" ? 10 : target.x - 2, top: mood === "listen" ? 10 : target.y - 2,
            width: mood === "listen" ? 74 : target.width + 4, height: mood === "listen" ? 58 : target.height + 4 }}>
            <span>Vico · {text}</span>
            {mood === "work" && <i className="mini-ghost" />}
          </div>
        )}
      </div>
      <p className="mini-label">{label || " "}</p>
    </div>
  );
}

const NAMES: Record<Look, { name: string; line: string }> = {
  peek: { name: "Peek", line: "Holds the bottom edge, then leaps to whatever it clicks or types into." },
  possession: { name: "Possession", line: "No body. Lights up the window it is using; a ghost cursor does the clicking." },
  yoyo: { name: "Yo-yo", line: "Hangs from the top edge and drops onto whatever it is working on." },
};

export function LookPicker({ value, onChange }: { value: Look | null; onChange: (look: Look) => void }) {
  return (
    <div className="looks" role="radiogroup" aria-label="How Vico appears">
      {(Object.keys(NAMES) as Look[]).map((look) => (
        <button
          type="button"
          key={look}
          role="radio"
          aria-checked={value === look}
          className={`look ${value === look ? "chosen" : ""}`}
          onClick={() => onChange(look)}
          data-testid={`look-${look}`}
        >
          <LookPreview look={look} />
          <strong>{NAMES[look].name}</strong>
          <span>{NAMES[look].line}</span>
        </button>
      ))}
    </div>
  );
}
