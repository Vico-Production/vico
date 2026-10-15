// Where Vico appears on screen for each look, in CSS pixels of the full-screen aura window.
// The prompt window (the only part that takes the keyboard) is placed next to the look.

export type Look = "peek" | "possession" | "yoyo";
export const LOOKS: Look[] = ["peek", "possession", "yoyo"];

export interface Rect {
  x: number;
  y: number;
  width: number;
  height: number;
}

/** How the look behaves right now, derived from the session phase. */
export type Mood = "away" | "listen" | "think" | "work" | "ask" | "done" | "sad";

export const PEEK_W = 100; // the peeking figure, drawn at the bottom edge
export const PEEK_H = 82;
export const YOYO_X_FROM_RIGHT = 110; // the yo-yo hangs this far from the right edge
export const ORB = 58;
const GAP = 14;

const clamp = (v: number, lo: number, hi: number) => Math.max(lo, Math.min(hi, v));

/** Prompt window size for a phase. */
export function promptSize(phase: string, screen: { width: number; height: number }) {
  if (phase === "setup" || phase === "settings") {
    const tall = phase === "settings" ? 680 : 540;
    return { width: Math.min(780, screen.width - 40), height: Math.min(tall, screen.height - 60) };
  }
  if (phase === "approval") return { width: 480, height: 210 };
  if (phase === "question") return { width: 460, height: 176 };
  return { width: 460, height: 138 };
}

/** Peek walks along the bottom edge towards the window it is working in. */
export function peekCenter(mood: Mood, screen: { width: number }, target: Rect | null): number {
  const home = screen.width * 0.5;
  if ((mood === "work" || mood === "ask") && target) {
    return clamp(target.x + target.width / 2, PEEK_W, screen.width - PEEK_W);
  }
  return home;
}

export function yoyoLength(mood: Mood): number {
  if (mood === "away") return 0;
  return mood === "work" ? 150 : 112;
}

/** Possession needs a real window to inhabit; tiny or off-screen ones don't count. */
export function usableTarget(target: Rect | null, screen: { width: number; height: number }): Rect | null {
  if (!target || target.width < 160 || target.height < 100) return null;
  const x = clamp(target.x, 0, screen.width - 160);
  const y = clamp(target.y, 0, screen.height - 100);
  return { x, y, width: Math.min(target.width, screen.width - x), height: Math.min(target.height, screen.height - y) };
}

/** Where the prompt window goes, next to (or inside, for Possession) the look. */
export function promptFrame(
  look: Look,
  phase: string,
  mood: Mood,
  screen: { width: number; height: number },
  target: Rect | null,
): Rect {
  const { width, height } = promptSize(phase, screen);
  if (phase === "setup" || phase === "settings") {
    return { x: (screen.width - width) / 2, y: (screen.height - height) / 2, width, height };
  }
  let x: number;
  let y: number;
  if (look === "peek") {
    x = peekCenter(mood, screen, target) - width / 2;
    y = screen.height - PEEK_H - GAP - height;
  } else if (look === "yoyo") {
    x = screen.width - YOYO_X_FROM_RIGHT - ORB / 2 - GAP - width;
    y = yoyoLength(mood === "away" ? "listen" : mood) - 10;
  } else {
    const t = usableTarget(target, screen);
    if (t) {
      x = t.x + (t.width - width) / 2;
      y = t.y + 46;
    } else {
      x = (screen.width - width) / 2;
      y = 56;
    }
  }
  return {
    x: Math.round(clamp(x, 8, screen.width - width - 8)),
    y: Math.round(clamp(y, 8, screen.height - height - 8)),
    width,
    height,
  };
}
