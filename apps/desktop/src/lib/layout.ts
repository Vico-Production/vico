// Where Vico appears on screen for each look, in CSS pixels of the full-screen aura window.
// The prompt window (the only part that takes the keyboard) is placed next to the look.

export type Look = "peek" | "possession" | "yoyo" | "swarm" | "runner" | "lens";
export const LOOKS: Look[] = ["peek", "possession", "yoyo", "swarm", "runner", "lens"];

export interface Rect {
  x: number;
  y: number;
  width: number;
  height: number;
}

/** How the look behaves right now, derived from the session phase. */
export type Mood = "away" | "listen" | "think" | "work" | "ask" | "done" | "sad";

/** Where the user put each look: fractions of the screen width; the label 0 = top, 1 = bottom. */
export type SpotMap = Partial<Record<"peek" | "yoyo" | "possession_label" | "swarm" | "runner" | "lens", number>>;

export const PEEK_W = 100; // the peeking figure, drawn at the bottom edge
export const PEEK_H = 82;
export const ORB = 58;
const GAP = 14;

const clamp = (v: number, lo: number, hi: number) => Math.max(lo, Math.min(hi, v));

/** Prompt window size for a phase. */
export function promptSize(phase: string, screen: { width: number; height: number }) {
  if (phase === "setup" || phase === "settings") {
    const tall = 700; // six live previews and the mode switch fit without scrolling on a laptop
    return { width: Math.min(780, screen.width - 40), height: Math.min(tall, screen.height - 60) };
  }
  if (phase === "welcome") return { width: Math.min(680, screen.width - 40), height: 240 };
  if (phase === "approval") return { width: 480, height: 210 };
  if (phase === "question") return { width: 460, height: 176 };
  if (phase === "typing") return { width: 460, height: 150 };
  return { width: 420, height: 150 }; // listening, transcribing, review
}

/** Peek's home on the bottom edge (where the user left it, or the middle). */
export function peekHome(screen: { width: number }, spots?: SpotMap): number {
  return clamp((spots?.peek ?? 0.5) * screen.width, PEEK_W, screen.width - PEEK_W);
}

/** The yo-yo's anchor on the top edge (where the user left it, or near the right corner). */
export function yoyoHome(screen: { width: number }, spots?: SpotMap): number {
  const fallback = screen.width - 110;
  const x = spots?.yoyo !== undefined ? spots.yoyo * screen.width : fallback;
  return clamp(x, ORB, screen.width - ORB / 2 - 8);
}

/** Swarm and Lens rest near the bottom edge, where the user left them (or the middle). */
export function bottomHome(look: "swarm" | "lens", screen: { width: number; height: number }, spots?: SpotMap) {
  const x = clamp((spots?.[look] ?? 0.5) * screen.width, 140, screen.width - 140);
  return { x, y: screen.height - (look === "lens" ? 96 : 34) };
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
  spots?: SpotMap,
): Rect {
  const { width, height } = promptSize(phase, screen);
  if (phase === "setup" || phase === "settings" || phase === "welcome") {
    return { x: (screen.width - width) / 2, y: (screen.height - height) / 2, width, height };
  }
  let x: number;
  let y: number;
  if (look === "peek") {
    x = peekHome(screen, spots) - width / 2;
    y = screen.height - PEEK_H - GAP - height;
  } else if (look === "swarm" || look === "lens") {
    const home = bottomHome(look, screen, spots);
    x = home.x - width / 2;
    y = home.y - (look === "lens" ? 70 : 110) - GAP - height;
  } else if (look === "runner") {
    const t = usableTarget(target, screen);
    x = t ? t.x + (t.width - width) / 2 : (screen.width - width) / 2;
    y = t ? t.y + 46 : screen.height - 80 - height;
  } else if (look === "yoyo") {
    const anchor = yoyoHome(screen, spots);
    const leftSide = anchor > screen.width / 2;
    x = leftSide ? anchor - ORB / 2 - GAP - width : anchor + ORB / 2 + GAP;
    y = yoyoLength(mood === "away" ? "listen" : mood) - 10;
  } else {
    const t = usableTarget(target, screen);
    const bottom = (spots?.possession_label ?? 0) >= 0.5;
    if (t) {
      x = t.x + (t.width - width) / 2;
      y = bottom ? t.y + t.height - height - 30 : t.y + 46;
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
