// Swarm, Window runner and Lens: three looks drawn on a canvas, from the same moods, reactions
// and acted-out steps as the other looks. Positions come only from the engine (the step's
// stage and the window in use); with none, the look acts the step out at home.
import { useEffect, useRef, useState, type PointerEvent as ReactPointerEvent } from "react";
import type { Act } from "../lib/acting";
import { actPoint } from "../lib/acting";
import type { Mood, Rect } from "../lib/layout";
import { native } from "../lib/native";
import type { Reaction } from "./Looks";

export type CanvasLookName = "swarm" | "runner" | "lens";
type Pt = { x: number; y: number };

export interface World {
  width: number;
  height: number;
  home: Pt; // where the look rests
  target: Rect | null; // the window in use
  act: Act | null; // the step being acted out
  mood: Mood;
  reaction: Reaction | null;
  level: number; // the voice level, 0..1
  dodge: Pt | null; // the slowing cursor the body moves away from
}

const TAU = Math.PI * 2;
const lerp = (a: number, b: number, u: number) => a + (b - a) * u;
const clamp01 = (u: number) => Math.max(0, Math.min(1, u));
const ease = (u: number) => (u < 0.5 ? 2 * u * u : 1 - Math.pow(-2 * u + 2, 2) / 2);
const TRAVEL_S = 0.4; // travel stays within the 300-450 ms budget and never delays a step

function rr(ctx: CanvasRenderingContext2D, x: number, y: number, w: number, h: number, r: number) {
  ctx.beginPath();
  ctx.roundRect(x, y, w, h, r);
}

function glyph(ctx: CanvasRenderingContext2D, reaction: Reaction | null, x: number, y: number, t: number) {
  ctx.save();
  ctx.font = "700 16px 'Segoe UI', sans-serif";
  ctx.textAlign = "center";
  if (reaction === "huh") {
    ctx.fillStyle = "#5DCAA5";
    ctx.font = "700 26px 'Segoe UI', sans-serif";
    ctx.fillText("?", x, y);
  } else if (reaction === "doze") {
    ctx.fillStyle = "rgba(157,179,172," + (0.4 + 0.4 * Math.sin(t * 2)).toFixed(2) + ")";
    ctx.fillText("z z z", x, y - ((t * 8) % 14));
  } else if (reaction === "stay") {
    ctx.strokeStyle = "#D85A30";
    ctx.lineWidth = 2.4;
    ctx.beginPath();
    ctx.arc(x, y - 10, 6, 0, TAU);
    ctx.moveTo(x, y - 4);
    ctx.lineTo(x, y + 8);
    ctx.stroke();
  }
  ctx.restore();
}

function tick(ctx: CanvasRenderingContext2D, x: number, y: number, size: number, alpha: number) {
  ctx.save();
  ctx.globalAlpha = alpha;
  ctx.lineWidth = Math.max(3, size / 9);
  ctx.lineCap = "round";
  ctx.strokeStyle = "#5DCAA5";
  ctx.beginPath();
  ctx.moveTo(x - size * 0.32, y);
  ctx.lineTo(x - size * 0.08, y + size * 0.24);
  ctx.lineTo(x + size * 0.36, y - size * 0.26);
  ctx.stroke();
  ctx.restore();
}

/** Memory that persists between frames (particles, travel, where the look is). */
export interface Memory {
  t0: number;
  stateSince: number;
  lastKey: string;
  particles: { x: number; y: number; vx: number; vy: number; ph: number }[];
  at: Pt | null; // where the look is now (runner, lens)
  from: Pt | null;
  travelAt: number;
  actKey: string;
  r: number;
}

export function newMemory(home: Pt): Memory {
  return {
    t0: performance.now(), stateSince: performance.now(), lastKey: "", actKey: "", travelAt: 0, from: null,
    at: null, r: 0,
    particles: Array.from({ length: 70 }, () => ({ x: home.x + (Math.random() - 0.5) * 260, y: home.y + 60, vx: 0,
      vy: 0, ph: Math.random() * TAU })),
  };
}

function stateKey(w: World) {
  return `${w.mood}|${w.reaction ?? ""}`;
}

/** Travelling from wherever the look is to a new spot, in TRAVEL_S, with a hop. */
function travel(mem: Memory, w: World, goal: Pt, now: number, key: string): Pt {
  if (mem.actKey !== key) {
    mem.actKey = key;
    mem.from = mem.at ?? goal;
    mem.travelAt = now;
  }
  const u = clamp01((now - mem.travelAt) / 1000 / TRAVEL_S);
  const from = mem.from ?? goal;
  const e = ease(u);
  const hop = Math.sin(u * Math.PI) * Math.min(90, Math.hypot(goal.x - from.x, goal.y - from.y) * 0.25);
  mem.at = { x: lerp(from.x, goal.x, e), y: lerp(from.y, goal.y, e) - hop };
  void w;
  return mem.at;
}

// --- Swarm: about seventy lights ----------------------------------------------------------------

function swarmTarget(i: number, n: number, w: World, t: number, st: number): Pt {
  const { home } = w;
  const point = w.act ? actPoint(w.act) : null;
  const r = w.reaction;
  if (w.mood === "away" || r === "bye") return { x: home.x + (i - n / 2) * 5, y: w.height + 40 };
  if (r === "shrug") return { x: home.x - 120 + (i / n) * 240, y: home.y + 22 + Math.sin(i) * 3 };
  if (r === "doze") return { x: home.x - 60 + (i / n) * 120, y: home.y + 10 + Math.sin(t * 1.5 + i) * 4 };
  if (w.mood === "done" || r === "celebrate") {
    const pts = [[-44, -10], [-12, 24], [52, -50]];
    const seg = (i / (n - 1)) * 2;
    const s = Math.min(1, Math.floor(seg));
    const f = seg - s;
    return { x: home.x + lerp(pts[s][0], pts[s + 1][0], f), y: home.y - 60 + lerp(pts[s][1], pts[s + 1][1], f) };
  }
  if (w.mood === "work" && w.act?.rect && point) {
    // outline the real control before pressing it
    const rect = w.act.kind === "element" || w.act.kind === "field" ? w.act.rect
      : { x: point.x - 60, y: point.y - 14, width: 120, height: 28 };
    const L = rect.x - 6, T = rect.y - 6, W = rect.width + 12, H = rect.height + 12, per = 2 * (W + H);
    let q = ((i / n) * per + t * 60) % per;
    if (q < W) return { x: L + q, y: T };
    q -= W;
    if (q < H) return { x: L + W, y: T + q };
    q -= H;
    if (q < W) return { x: L + W - q, y: T + H };
    q -= W;
    return { x: L, y: T + H - q };
  }
  if (w.mood === "think" || w.mood === "work" || w.mood === "ask") {
    const speed = w.mood === "ask" ? 0.6 : 2.4;
    const a = (i / n) * TAU + t * speed;
    const rad = 44 + (w.mood === "work" ? 6 * Math.sin(t * 6) : 0);
    return { x: home.x + Math.cos(a) * rad, y: home.y - 60 + Math.sin(a) * rad };
  }
  // listening: a wave along the bottom edge that traces the voice
  const x = home.x - 230 + i * (460 / n);
  const voice = 0.25 + Math.min(1, w.level * 5);
  const amp = 30 * voice * Math.exp(-(((x - home.x) / 230) ** 2));
  return { x, y: home.y + Math.sin(i * 0.42 + t * 8) * amp + (r === "arrive" ? Math.max(0, 1 - st * 2) * 80 : 0) };
}

export function drawSwarm(ctx: CanvasRenderingContext2D, w: World, mem: Memory, now: number) {
  const t = (now - mem.t0) / 1000;
  const st = (now - mem.stateSince) / 1000;
  const n = mem.particles.length;
  const fast = w.mood === "work" || w.mood === "done";
  const shake = w.reaction === "refuse" ? Math.sin(t * 40) * 6 : 0;
  for (let i = 0; i < n; i++) {
    const p = mem.particles[i];
    const g = swarmTarget(i, n, w, t, st);
    const k = fast ? 0.09 : 0.05;
    let fx = (g.x + shake - p.x) * k;
    let fy = (g.y - p.y) * k;
    if (w.dodge) {
      // scatter from a slowing cursor
      const dx = p.x - w.dodge.x;
      const dy = p.y - w.dodge.y;
      const d = Math.hypot(dx, dy);
      if (d < 120) {
        fx += (dx / (d || 1)) * (120 - d) * 0.09;
        fy += (dy / (d || 1)) * (120 - d) * 0.09;
      }
    }
    p.vx = (p.vx + fx + Math.sin(t * 3 + p.ph) * 0.3) * 0.78;
    p.vy = (p.vy + fy + Math.cos(t * 2.6 + p.ph) * 0.3) * 0.78;
    p.x += p.vx;
    p.y += p.vy;
    const tw = 0.6 + 0.4 * Math.sin(t * 6 + p.ph);
    const glow = w.reaction === "cooling" ? "133,183,235" : w.reaction === "refuse" ? "216,90,48" : "239,159,39";
    const dim = w.reaction === "doze" || w.reaction === "shrug" ? 0.45 : 1;
    ctx.beginPath();
    ctx.arc(p.x, p.y, 7, 0, TAU);
    ctx.fillStyle = `rgba(${glow},${(0.2 * tw * dim).toFixed(3)})`;
    ctx.fill();
    ctx.beginPath();
    ctx.arc(p.x, p.y, 2.6, 0, TAU);
    ctx.fillStyle = w.mood === "work" ? "#0F6E56" : w.reaction === "cooling" ? "#378ADD" : "#BA7517";
    ctx.globalAlpha = dim;
    ctx.fill();
    ctx.globalAlpha = 1;
  }
  if (w.mood === "work" && w.act?.rect && Math.sin(st * 9) > 0.6) {
    const p = actPoint(w.act);
    if (p) {
      ctx.beginPath();
      ctx.arc(p.x, p.y, 10 + (st * 30) % 16, 0, TAU);
      ctx.strokeStyle = "rgba(239,159,39,.8)";
      ctx.lineWidth = 2.5;
      ctx.stroke();
    }
  }
  glyph(ctx, w.reaction, w.home.x + 70, w.home.y - 70, t);
}

// --- Window runner: a tiny character on the title bars ------------------------------------------

export function runnerHome(w: Pick<World, "target" | "height">, homeX: number, spot: number | undefined): Pt {
  if (w.target) {
    const x = w.target.x + Math.max(30, Math.min(w.target.width - 30, (spot ?? 0.3) * w.target.width));
    return { x, y: w.target.y };
  }
  return { x: homeX, y: w.height };
}

export function drawRunner(ctx: CanvasRenderingContext2D, w: World, mem: Memory, now: number) {
  const t = (now - mem.t0) / 1000;
  const st = (now - mem.stateSince) / 1000;
  if (w.mood === "away" && w.reaction !== "bye") {
    mem.at = null;
    return;
  }
  const point = w.act ? actPoint(w.act) : null;
  let goal = w.home;
  if (w.dodge) goal = { x: w.home.x + (w.dodge.x < w.home.x ? 60 : -60), y: w.home.y }; // hops aside
  if (point && w.act?.rect) {
    // drop onto the control, or stand on the window's title bar
    goal = w.act.kind === "element" || w.act.kind === "field" ? { x: point.x, y: w.act.rect.y } : point;
  }
  const key = point ? `${w.act?.id}:${Math.round(goal.x)},${Math.round(goal.y)}` : `home:${Math.round(goal.x)}`;
  const pos = travel(mem, w, goal, now, key);
  const arrived = now - mem.travelAt > TRAVEL_S * 1000;
  const stomp = Boolean(point && w.act?.rect && arrived && now - mem.travelAt < TRAVEL_S * 1000 + 450);
  let { x, y } = pos;
  if (w.reaction === "bye") y += Math.min(1, st) * 80;
  if (w.mood === "listen" || w.reaction === "arrive") y -= Math.abs(Math.sin(t * 10)) * 5;
  if (w.mood === "done" || w.reaction === "celebrate") y -= Math.abs(Math.sin(st * 7)) * 22 * Math.max(0, 1 - st / 1.8);
  if (w.reaction === "refuse") x += Math.sin(t * 40) * 4;
  const running = !arrived;
  const leg = running ? Math.sin(t * 28) * 5 : 0;
  ctx.fillStyle = "#04342C";
  ctx.fillRect(x - 9 + leg * 0.5, y - 9, 6, 9);
  ctx.fillRect(x + 3 - leg * 0.5, y - 9, 6, 9);
  rr(ctx, x - 14, y - 40, 28, 32, 10);
  ctx.fillStyle = w.reaction === "cooling" ? "#378ADD" : "#1D9E75";
  ctx.fill();
  ctx.fillStyle = "#FFFFFF";
  ctx.beginPath();
  ctx.arc(x - 5, y - 27, 5, 0, TAU);
  ctx.arc(x + 6, y - 27, 5, 0, TAU);
  ctx.fill();
  const happy = w.mood === "done" || w.reaction === "celebrate" || w.reaction === "greet";
  if (happy) {
    ctx.strokeStyle = "#04342C";
    ctx.lineWidth = 2.4;
    for (const ex of [x - 5, x + 6]) {
      ctx.beginPath();
      ctx.arc(ex, y - 25, 3.5, Math.PI * 1.1, Math.PI * 1.9);
      ctx.stroke();
    }
  } else {
    const look = w.mood === "think" ? Math.sin(t * 3) * 2.5 : w.reaction === "shrug" || w.reaction === "huh" ? 0 : 2;
    const down = w.reaction === "shrug" || w.reaction === "huh" ? 2 : 0;
    ctx.fillStyle = "#04342C";
    ctx.beginPath();
    ctx.arc(x - 5 + look, y - 27 + down, 2.5, 0, TAU);
    ctx.arc(x + 6 + look, y - 27 + down, 2.5, 0, TAU);
    ctx.fill();
    if (w.reaction === "doze" || w.reaction === "cooling") {
      ctx.fillStyle = w.reaction === "cooling" ? "#378ADD" : "#1D9E75";
      ctx.fillRect(x - 11, y - 33, 22, 6);
    }
  }
  if (w.mood === "listen") {
    ctx.strokeStyle = "#1D9E75";
    ctx.lineWidth = 2.4;
    for (let k = 0; k < 3; k++) {
      const a = (t * 2 + k / 3) % 1;
      ctx.globalAlpha = (1 - a) * (0.4 + Math.min(1, w.level * 5) * 0.6);
      ctx.beginPath();
      ctx.arc(x, y - 40, 10 + a * 24, Math.PI * 1.25, Math.PI * 1.75);
      ctx.stroke();
    }
    ctx.globalAlpha = 1;
  }
  if (w.mood === "think" || (w.mood === "work" && !w.act?.rect)) {
    ctx.fillStyle = "#9DB3AC";
    for (let k = 0; k < 3; k++) {
      ctx.globalAlpha = Math.floor(t * 3) % 3 === k ? 1 : 0.3;
      ctx.beginPath();
      ctx.arc(x - 9 + k * 9, y - 54, 3, 0, TAU);
      ctx.fill();
    }
    ctx.globalAlpha = 1;
  }
  if (w.reaction === "greet" || w.reaction === "bye") {
    ctx.strokeStyle = "#5DCAA5";
    ctx.lineWidth = 4;
    ctx.lineCap = "round";
    ctx.beginPath();
    ctx.moveTo(x + 14, y - 30);
    ctx.lineTo(x + 24, y - 44 + Math.sin(t * 14) * 4);
    ctx.stroke();
  }
  if (stomp) {
    ctx.strokeStyle = "#EF9F27";
    ctx.lineWidth = 2.4;
    for (let k = -1; k <= 1; k++) {
      ctx.beginPath();
      ctx.moveTo(x + k * 18, y + 3);
      ctx.lineTo(x + k * 28, y + 11);
      ctx.stroke();
    }
  }
  glyph(ctx, w.reaction, x + 26, y - 46, t);
}

// --- Lens: liquid glass over the real screen ------------------------------------------------------

export const LENS_R = 56;

export function lensGoal(w: World, mem: Memory, now: number): { x: number; y: number; r: number } {
  const t = (now - mem.t0) / 1000;
  const st = (now - mem.stateSince) / 1000;
  const { home } = w;
  if (w.mood === "away" || w.reaction === "bye") return { x: home.x, y: w.height + 80, r: 0 };
  const point = w.act ? actPoint(w.act) : null;
  if (w.dodge) return { x: home.x + (w.dodge.x < home.x ? 140 : -140), y: home.y, r: LENS_R }; // slides away
  if (w.mood === "work" && point && w.act?.rect) return { x: point.x, y: point.y, r: 54 };
  if ((w.mood === "think" || (w.mood === "work" && !w.act?.rect)) && w.target) {
    // glide along the window's lines of text
    const tg = w.target;
    const u = (st * 0.45) % 1;
    const line = Math.floor((st * 0.45) % 5);
    return { x: tg.x + 70 + u * Math.max(40, tg.width - 140), y: tg.y + 60 + line * 24, r: 52 };
  }
  if (w.mood === "done" || w.reaction === "celebrate") {
    const lift = Math.min(1, st / 0.6) * 60;
    return { x: mem.at?.x ?? home.x, y: (mem.at?.y ?? home.y) - lift, r: Math.max(0, LENS_R * (1 - Math.max(0, st - 1.3) / 0.6)) };
  }
  return { x: home.x, y: home.y, r: LENS_R + (w.mood === "listen" ? 6 * Math.min(1, w.level * 5) : 0) + Math.sin(t * 2) };
}

export function drawLens(ctx: CanvasRenderingContext2D, w: World, mem: Memory, now: number, magnified: boolean) {
  const t = (now - mem.t0) / 1000;
  const st = (now - mem.stateSince) / 1000;
  const goal = lensGoal(w, mem, now);
  const at = mem.at ?? { x: goal.x, y: goal.y };
  const k = w.mood === "work" ? 0.3 : 0.16;
  mem.at = { x: at.x + (goal.x - at.x) * k, y: at.y + (goal.y - at.y) * k };
  mem.r += (goal.r - mem.r) * 0.2;
  const { x, y } = mem.at;
  const r = mem.r;
  if (r < 2) return { x, y, r: 0 };
  const shake = w.reaction === "refuse" ? Math.sin(t * 40) * 5 : 0;
  const cx = x + shake;
  if (!magnified) {
    // Clear glass: this computer cannot magnify the screen, and the Lens does not pretend to.
    ctx.save();
    ctx.beginPath();
    ctx.arc(cx, y, r, 0, TAU);
    ctx.clip();
    ctx.fillStyle = "rgba(159,225,203,.10)";
    ctx.fillRect(cx - r, y - r, 2 * r, 2 * r);
    ctx.beginPath();
    ctx.ellipse(cx - r * 0.32, y - r * 0.42, r * 0.42, r * 0.16, -0.6, 0, TAU);
    ctx.fillStyle = "rgba(255,255,255,.30)";
    ctx.fill();
    ctx.restore();
  }
  // the rim sits just outside the magnified disc, so it is never under the magnifier
  const tint = w.reaction === "cooling" ? "133,183,235" : w.reaction === "refuse" ? "216,90,48"
    : w.mood === "ask" ? "239,159,39" : "255,255,255";
  ctx.beginPath();
  ctx.arc(cx, y, r + 2, 0, TAU);
  ctx.lineWidth = 3;
  ctx.strokeStyle = `rgba(${tint},.9)`;
  ctx.stroke();
  ctx.beginPath();
  ctx.arc(cx, y, r + 4.5, 0, TAU);
  ctx.lineWidth = 1.5;
  ctx.strokeStyle = "rgba(4,52,44,.5)";
  ctx.stroke();
  if (w.mood === "listen") {
    for (let k2 = 0; k2 < 3; k2++) {
      const a = (t * 1.4 + k2 / 3) % 1;
      ctx.beginPath();
      ctx.arc(cx, y, r + 6 + a * 30, 0, TAU);
      ctx.lineWidth = 1.5;
      ctx.strokeStyle = `rgba(29,158,117,${(0.5 * (1 - a) * (0.4 + Math.min(1, w.level * 5) * 0.6)).toFixed(3)})`;
      ctx.stroke();
    }
  }
  if (w.mood === "work" && w.act?.rect && Math.sin(st * 12) > 0.6) {
    ctx.beginPath();
    ctx.arc(cx, y, r + 9, 0, TAU);
    ctx.lineWidth = 3;
    ctx.strokeStyle = "rgba(239,159,39,.85)";
    ctx.stroke();
  }
  if (w.mood === "done" || w.reaction === "celebrate") tick(ctx, cx + r + 24, y - r, 34, Math.min(1, st / 0.4));
  glyph(ctx, w.reaction, cx + r + 18, y - r + 6, t);
  return { x: cx, y, r };
}

// --- the avatar on screen --------------------------------------------------------------------

export function CanvasAvatar({ look, world, onGrab, onMagnifier }: {
  look: CanvasLookName;
  world: World;
  onGrab: (e: ReactPointerEvent) => void;
  onMagnifier?: (available: boolean) => void;
}) {
  const canvas = useRef<HTMLCanvasElement>(null);
  const live = useRef(world);
  live.current = world;
  const mem = useRef<Memory>(newMemory(world.home));
  const [handle, setHandle] = useState<Rect | null>(null);

  useEffect(() => {
    const cv = canvas.current;
    const ctx = cv?.getContext("2d");
    if (!cv || !ctx) return;
    let frame = 0;
    let lensSent = 0;
    let magnifier: boolean | null = null;
    let lastHandle = "";
    const draw = (now: number) => {
      const w = live.current;
      const dpr = window.devicePixelRatio || 1;
      if (cv.width !== w.width * dpr || cv.height !== w.height * dpr) {
        cv.width = w.width * dpr;
        cv.height = w.height * dpr;
      }
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
      ctx.clearRect(0, 0, w.width, w.height);
      const key = stateKey(w);
      if (key !== mem.current.lastKey) {
        mem.current.lastKey = key;
        mem.current.stateSince = now;
      }
      let box: Rect | null = null;
      if (look === "swarm") {
        drawSwarm(ctx, w, mem.current, now);
        box = { x: w.home.x - 70, y: w.height - 16, width: 140, height: 16 }; // the nest
      } else if (look === "runner") {
        drawRunner(ctx, w, mem.current, now);
        const at = mem.current.at;
        box = at ? { x: at.x - 16, y: at.y - 42, width: 32, height: 44 } : null;
      } else {
        const lens = drawLens(ctx, w, mem.current, now, magnifier !== false);
        box = lens.r > 2 ? { x: lens.x - lens.r - 6, y: lens.y - lens.r - 6, width: 2 * lens.r + 12, height: 2 * lens.r + 12 } : null;
        // Magnify the real screen under the glass (Windows Magnification API), ~30 times a second.
        if (now - lensSent > 33) {
          lensSent = now;
          if (lens.r > 2 && native.lensShow) {
            void native.lensShow(lens.x, lens.y, lens.r, w.mood === "work" ? 1.9 : 1.6).then((ok) => {
              if (magnifier !== ok) {
                magnifier = ok;
                onMagnifier?.(ok);
              }
            });
          } else if (lens.r <= 2) {
            void native.lensHide?.();
          } else if (magnifier === null) {
            magnifier = false;
            onMagnifier?.(false);
          }
        }
      }
      const handleKey = box ? `${Math.round(box.x / 4)},${Math.round(box.y / 4)},${Math.round(box.width)}` : "";
      if (handleKey !== lastHandle) {
        lastHandle = handleKey;
        setHandle(box);
      }
      frame = requestAnimationFrame(draw);
    };
    frame = requestAnimationFrame(draw);
    return () => {
      cancelAnimationFrame(frame);
      if (look === "lens") void native.lensHide?.();
    };
  }, [look]); // eslint-disable-line react-hooks/exhaustive-deps

  return (
    <>
      <canvas ref={canvas} className="look-canvas" style={{ width: world.width, height: world.height }} aria-hidden="true" />
      {handle && (
        <div className={`handle canvas-handle ${look}`} onPointerDown={onGrab} data-testid="avatar-handle"
          style={{ left: handle.x, top: handle.y, width: handle.width, height: handle.height }} />
      )}
    </>
  );
}

// --- previews in setup ---------------------------------------------------------------------

const MINI: { mood: Mood; reaction: Reaction | null; label: string; ms: number }[] = [
  { mood: "listen", reaction: "arrive", label: "Listening", ms: 2000 },
  { mood: "think", reaction: null, label: "Thinking", ms: 1500 },
  { mood: "work", reaction: null, label: "Working", ms: 2400 },
  { mood: "done", reaction: "celebrate", label: "Done", ms: 1700 },
  { mood: "away", reaction: null, label: "", ms: 600 },
];

/** A small screen that plays one canvas look through a whole task, over and over. */
export function MiniCanvasPreview({ look }: { look: CanvasLookName }) {
  const canvas = useRef<HTMLCanvasElement>(null);
  const [i, setI] = useState(0);
  const step = useRef(0);
  step.current = i;
  useEffect(() => {
    const id = window.setTimeout(() => setI((n) => (n + 1) % MINI.length), MINI[i].ms);
    return () => window.clearTimeout(id);
  }, [i]);
  useEffect(() => {
    const cv = canvas.current;
    const ctx = cv?.getContext("2d");
    if (!cv || !ctx) return;
    // drawn at 2x the box, then scaled down, so the look keeps its real proportions
    const W = 428;
    const H = 248;
    const winA: Rect = { x: 20, y: 20, width: 148, height: 116 };
    const winB: Rect = { x: 184, y: 44, width: 236, height: 164 };
    const button: Rect = { x: 330, y: 168, width: 70, height: 24 };
    const mem = newMemory({ x: W / 2, y: H - 40 });
    let frame = 0;
    const dpr = window.devicePixelRatio || 1;
    cv.width = 214 * dpr;
    cv.height = 124 * dpr;
    const draw = (now: number) => {
      const { mood, reaction } = MINI[step.current];
      ctx.setTransform(dpr * 0.5, 0, 0, dpr * 0.5, 0, 0);
      ctx.fillStyle = "#1E2A27";
      ctx.fillRect(0, 0, W, H);
      for (const wn of [winA, winB]) {
        rr(ctx, wn.x, wn.y, wn.width, wn.height, 8);
        ctx.fillStyle = "#2E3D39";
        ctx.fill();
        ctx.fillStyle = "#3A4C47";
        rr(ctx, wn.x, wn.y, wn.width, 14, 8);
        ctx.fill();
      }
      rr(ctx, button.x, button.y, button.width, button.height, 6);
      ctx.fillStyle = "#D85A30";
      ctx.fill();
      const act: Act | null = mood === "work" ? { id: "demo", motion: "tap", kind: "element", rect: button, running: true } : null;
      const homeY = look === "lens" ? H - 60 : H - 34;
      const world: World = {
        width: W, height: H, home: look === "runner" ? { x: winB.x + 60, y: winB.y } : { x: W / 2, y: homeY },
        target: winB, act, mood, reaction, level: mood === "listen" ? 0.12 + 0.1 * Math.sin(now / 160) : 0, dodge: null,
      };
      const key = stateKey(world);
      if (key !== mem.lastKey) {
        mem.lastKey = key;
        mem.stateSince = now;
      }
      if (look === "swarm") drawSwarm(ctx, world, mem, now);
      else if (look === "runner") drawRunner(ctx, world, mem, now);
      else {
        if (mem.at && mem.r > 2) {
          // in the preview, show what the glass does by drawing the scene under it enlarged
          const { x, y } = mem.at;
          ctx.save();
          ctx.beginPath();
          ctx.arc(x, y, mem.r, 0, TAU);
          ctx.clip();
          ctx.fillStyle = "#1E2A27";
          ctx.fillRect(x - mem.r, y - mem.r, 2 * mem.r, 2 * mem.r);
          ctx.translate(x, y);
          ctx.scale(1.7, 1.7);
          ctx.translate(-x, -y);
          for (const wn of [winA, winB]) {
            rr(ctx, wn.x, wn.y, wn.width, wn.height, 8);
            ctx.fillStyle = "#2E3D39";
            ctx.fill();
          }
          rr(ctx, button.x, button.y, button.width, button.height, 6);
          ctx.fillStyle = "#D85A30";
          ctx.fill();
          ctx.restore();
        }
        drawLens(ctx, world, mem, now, true);
      }
      frame = requestAnimationFrame(draw);
    };
    frame = requestAnimationFrame(draw);
    return () => cancelAnimationFrame(frame);
  }, [look]);
  return (
    <div className="mini" aria-hidden="true">
      <div className="mini-screen">
        <canvas ref={canvas} style={{ width: 214, height: 124, display: "block" }} />
      </div>
      <p className="mini-label">{MINI[i].label || " "}</p>
    </div>
  );
}
