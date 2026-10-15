// Vico's three looks. Each is drawn from the same moods (listen, think, work, ask, done),
// so the full-screen aura and the small previews in setup always match.
import { useEffect, useState } from "react";
import type { Look, Mood, Rect } from "../lib/layout";

/** A little creature holding the bottom edge of the screen and peeking over it. */
export function PeekFigure({ mood, level = 0, width = 100 }: { mood: Mood; level?: number; width?: number }) {
  const mouth = 3 + Math.min(1, level * 4) * 4;
  return (
    <svg className={`peek-figure mood-${mood}`} width={width} height={width * 0.82} viewBox="0 0 80 66" aria-hidden="true">
      <g className="peek-body">
        <rect x="10" y="4" width="60" height="64" rx="28" fill="#1D9E75" />
        <g className="eyes">
          <circle cx="30" cy="27" r="9" fill="#fff" />
          <circle cx="50" cy="27" r="9" fill="#fff" />
          <circle className="pupil" cx="30" cy="28" r="4" fill="#04342C" />
          <circle className="pupil" cx="50" cy="28" r="4" fill="#04342C" />
          <path className="happy" d="M23 29 Q30 21 37 29 M43 29 Q50 21 57 29" stroke="#04342C" strokeWidth="3" fill="none"
            strokeLinecap="round" />
        </g>
        <ellipse className="mouth-o" cx="40" cy="46" rx="4" ry={mouth} fill="#04342C" />
        <path className="mouth-smile" d="M32 44 Q40 52 48 44" stroke="#04342C" strokeWidth="3" fill="none" strokeLinecap="round" />
        <path className="mouth-flat" d="M34 47 H46" stroke="#04342C" strokeWidth="3" strokeLinecap="round" />
      </g>
      <ellipse cx="9" cy="61" rx="9" ry="6" fill="#5DCAA5" />
      <ellipse cx="71" cy="61" rx="9" ry="6" fill="#5DCAA5" />
    </svg>
  );
}

/** A yo-yo hanging from the top edge on a thread. */
export function YoyoFigure({ mood, length, size = 58 }: { mood: Mood; length: number; size?: number }) {
  return (
    <div className={`yoyo-figure mood-${mood}`} style={{ ["--len" as string]: `${length}px` }} aria-hidden="true">
      <div className="thread" />
      <svg className="orb" width={size} height={size} viewBox="0 0 46 46">
        <circle cx="23" cy="23" r="21" fill="#1D9E75" />
        <path d="M3 23 H43" stroke="#0F6E56" strokeWidth="2" />
        <circle cx="16" cy="15" r="6" fill="#fff" />
        <circle cx="30" cy="15" r="6" fill="#fff" />
        <circle className="pupil" cx="16" cy="16" r="3" fill="#04342C" />
        <circle className="pupil" cx="30" cy="16" r="3" fill="#04342C" />
        <path className="happy" d="M11 17 Q16 11 21 17 M25 17 Q30 11 35 17" stroke="#04342C" strokeWidth="2.4" fill="none"
          strokeLinecap="round" />
        <ellipse className="mouth-o" cx="23" cy="32" rx="3" ry="4" fill="#04342C" />
        <path className="mouth-smile" d="M17 31 Q23 37 29 31" stroke="#04342C" strokeWidth="2.4" fill="none" strokeLinecap="round" />
        <path className="mouth-flat" d="M18 33 H28" stroke="#04342C" strokeWidth="2.4" strokeLinecap="round" />
      </svg>
    </div>
  );
}

/** Possession: no body. Vico lights up the window it is using and narrates on its edge. */
export function PossessionFrame({ mood, rect, text, level = 0 }: { mood: Mood; rect: Rect | null; text: string; level?: number }) {
  if (!rect) {
    return (
      <div className={`possession-pill floating mood-${mood}`} data-testid="narration">
        <i className="dot" />
        <span>Vico{text ? ` · ${text}` : ""}</span>
      </div>
    );
  }
  return (
    <div
      className={`possession mood-${mood}`}
      style={{ left: rect.x, top: rect.y, width: rect.width, height: rect.height, ["--level" as string]: level.toFixed(3) }}
    >
      <svg className="edge" width={rect.width} height={rect.height} aria-hidden="true">
        <rect x="1.5" y="1.5" width={Math.max(0, rect.width - 3)} height={Math.max(0, rect.height - 3)} rx="9" className="edge-base" />
        <rect x="1.5" y="1.5" width={Math.max(0, rect.width - 3)} height={Math.max(0, rect.height - 3)} rx="9" className="edge-run"
          pathLength="100" />
      </svg>
      <div className={`possession-pill ${rect.y < 24 ? "inside" : ""}`} data-testid="narration">
        <i className="dot" />
        <span>Vico{text ? ` · ${text}` : ""}</span>
      </div>
    </div>
  );
}

const CYCLE: { mood: Mood; label: string; ms: number }[] = [
  { mood: "listen", label: "Listening", ms: 2000 },
  { mood: "think", label: "Thinking", ms: 1500 },
  { mood: "work", label: "Working", ms: 2400 },
  { mood: "done", label: "Done", ms: 1500 },
  { mood: "away", label: "", ms: 700 },
];
const PREVIEW_TEXT: Record<Mood, string> = {
  listen: "open my browser…",
  think: "on it",
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
  const { mood, label } = CYCLE[i];
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
            <div className="mini-peek" style={{ left: (mood === "work" ? 151 : 107) - 22 }}>
              <PeekFigure mood={mood} width={44} />
            </div>
            {visible && mood !== "done" && (
              <div className="mini-bubble centered" style={{ left: mood === "work" ? 151 : 107, bottom: 42 }}>{text}</div>
            )}
          </>
        )}
        {look === "yoyo" && (
          <>
            <div className="mini-yoyo">
              <YoyoFigure mood={mood} length={mood === "work" ? 62 : visible ? 46 : 0} size={28} />
            </div>
            {visible && mood !== "done" && <div className="mini-bubble" style={{ right: 52, top: 50 }}>{text}</div>}
          </>
        )}
        {look === "possession" && visible && (
          <div className={`mini-possess mood-${mood}`} style={{ left: mood === "listen" ? 10 : target.x - 2, top: mood === "listen" ? 10 : target.y - 2,
            width: mood === "listen" ? 74 : target.width + 4, height: mood === "listen" ? 58 : target.height + 4 }}>
            <span>Vico · {text}</span>
          </div>
        )}
      </div>
      <p className="mini-label">{label || " "}</p>
    </div>
  );
}

const NAMES: Record<Look, { name: string; line: string }> = {
  peek: { name: "Peek", line: "Holds the bottom edge and peeks over it, then walks to the app it is using." },
  possession: { name: "Possession", line: "No body. Lights up the window it is working in and talks on its edge." },
  yoyo: { name: "Yo-yo", line: "Drops from the top edge on a thread and swings while it works." },
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
