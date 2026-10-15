// Acting out the work: every real step goes through one of Vico's tools, so each tool has a
// motion. A task plays as a chain of these motions at the real on-screen spot, at the moment
// the step runs. Positions come only from the engine; when none is known the avatar acts the
// step out beside itself instead of guessing where to go.
import type { Step } from "./contracts";
import type { Rect } from "./layout";

export type Motion =
  | "tap" // click a control, press keys
  | "type" // sit on the field and bounce while the letters appear
  | "open" // go to the window; it grows from there
  | "navigate" // go to the address bar and type
  | "scroll" // pull the page
  | "bin" // carry the item to the Bin (after approval)
  | "pop" // a new folder or file pops into place
  | "carry" // move or copy
  | "read" // reading a page or file
  | "terminal" // typing on a tiny keyboard
  | "wait"; // a loading spinner

const MOTIONS: Record<string, Motion> = {
  click_element: "tap",
  press_keys: "tap",
  browser_click: "tap",
  browser_press: "tap",
  type_text: "type",
  browser_type: "type",
  focus_window: "open",
  open_app: "open",
  open_file: "open",
  open_url: "open",
  browser_open: "navigate",
  browser_back: "navigate",
  browser_scroll: "scroll",
  delete_path: "bin",
  create_folder: "pop",
  save_note: "pop",
  move_path: "carry",
  copy_path: "carry",
  browser_read: "read",
  read_text: "read",
  summarize_document: "read",
  list_folder: "read",
  find_files: "read",
  list_apps: "read",
  list_windows: "read",
  run_command: "terminal",
};

export function motionFor(tool: string): Motion {
  return MOTIONS[tool] ?? "wait";
}

/** Converts the engine's screen pixels into the aura's CSS pixels. */
export interface Metrics {
  x: number;
  y: number;
  scale: number;
}

export interface Act {
  id: string; // the step id: a new id is a new motion
  motion: Motion;
  kind: string; // element | field | window | titlebar | toolbar
  rect: Rect | null; // where on screen, in aura CSS pixels; null = act it out at home
  running: boolean;
}

export function toCss(rect: Rect, metrics: Metrics | null): Rect {
  if (!metrics) return rect; // browser preview: already in page pixels
  const s = metrics.scale || 1;
  return { x: (rect.x - metrics.x) / s, y: (rect.y - metrics.y) / s, width: rect.width / s, height: rect.height / s };
}

export function actFor(step: Step, metrics: Metrics | null): Act {
  const stage = step.stage;
  return {
    id: step.id,
    motion: motionFor(step.tool),
    kind: stage?.kind ?? "",
    rect: stage ? toCss(stage.rect, metrics) : null,
    running: step.status === "running",
  };
}

/** The exact point to act on: a control's centre, or a window's title bar. */
export function actPoint(act: Act): { x: number; y: number } | null {
  const r = act.rect;
  if (!r) return null;
  if (act.kind === "element" || act.kind === "field") return { x: r.x + r.width / 2, y: r.y + r.height / 2 };
  // window, titlebar, toolbar: the title bar near its left end, where the window "grows" from
  return { x: r.x + Math.min(90, r.width / 2), y: r.y + Math.min(16, r.height / 2) };
}
