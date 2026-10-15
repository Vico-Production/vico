// The aura: everything Vico draws over the whole screen. It never takes the keyboard or
// the mouse, so Vico can keep working in your apps while it glows.
import { useEffect, useRef, useState } from "react";
import { PROMPT_PHASES, type Phase, type Session } from "../lib/session";

const SVG_NS = "http://www.w3.org/2000/svg";
const POOL_LIFT = 118; // pool centre, px above the bottom edge
const FRAME = 7; // thickness of the liquid clinging to the screen frame

/** How strongly the liquid flows in each phase (drops per second before the voice boost). */
function dripRate(phase: Phase, level: number): number {
  switch (phase) {
    case "listening":
      return 1.8 + level * 16; // your voice makes it pour
    case "transcribing":
    case "thinking":
      return 1.2;
    case "working":
      return 0.9;
    case "cooling":
      return 0.15;
    case "setup":
    case "settings":
    case "typing":
    case "review":
    case "question":
    case "approval":
      return 0.55;
    default:
      return 0;
  }
}

/** Rising motes of light per second. */
function moteRate(phase: Phase, level: number): number {
  switch (phase) {
    case "listening":
      return 6 + level * 40;
    case "working":
    case "thinking":
    case "transcribing":
      return 9;
    case "done":
      return 26;
    case "cooling":
      return 1.5;
    case "hidden":
    case "leaving":
    case "error":
      return 0;
    default:
      return 3;
  }
}

const PRESENT: Phase[] = [
  "listening",
  "transcribing",
  "review",
  "typing",
  "thinking",
  "approval",
  "question",
  "working",
  "cooling",
  "done",
  "error",
  "setup",
  "settings",
];

interface Drop {
  el: SVGEllipseElement;
  x: number;
  y: number;
  r: number;
  rMax: number;
  vy: number;
  t: number;
  bead: number;
  falling: boolean;
  side: -1 | 0 | 1; // 0: falls from the top edge; ±1: a rivulet running down a side edge
}

interface Blob {
  el: SVGCircleElement;
  angle: number;
  speed: number;
  r: number;
}

interface Mote {
  el: SVGCircleElement;
  x: number;
  y: number;
  vx: number;
  vy: number;
  life: number;
  age: number;
  r: number;
  phase: number;
}

const MOTE_COLOURS = ["#ffffff", "#ffe7b0", "#9fe9ff", "#d4c6ff"];

/** Liquid light clinging to the screen frame, dripping into a pool, with motes rising. */
function Liquid({ session }: { session: Session }) {
  const svgRef = useRef<SVGSVGElement>(null);
  const live = useRef(session);
  live.current = session;

  useEffect(() => {
    const svg = svgRef.current;
    if (!svg) return;
    const reduced = window.matchMedia?.("(prefers-reduced-motion: reduce)").matches ?? false;
    const q = <T extends Element>(sel: string) => svg.querySelector<T>(sel)!;
    const dropsLayer = q<SVGGElement>("[data-layer=drops]");
    const poolLayer = q<SVGGElement>("[data-layer=pool]");
    const motesLayer = q<SVGGElement>("[data-layer=motes]");
    const top = q<SVGRectElement>("[data-edge=top]");
    const left = q<SVGRectElement>("[data-edge=left]");
    const right = q<SVGRectElement>("[data-edge=right]");
    const poolGradient = q<SVGRadialGradientElement>("#vico-pool");
    const shine = q<SVGEllipseElement>("[data-layer=shine]");
    const floor = q<SVGEllipseElement>("[data-layer=floor]");

    let width = window.innerWidth;
    let height = window.innerHeight;
    const resize = () => {
      width = window.innerWidth;
      height = window.innerHeight;
      svg.setAttribute("viewBox", `0 0 ${width} ${height}`);
    };
    resize();
    window.addEventListener("resize", resize);

    const core = document.createElementNS(SVG_NS, "ellipse");
    poolLayer.appendChild(core);
    const blobs: Blob[] = Array.from({ length: 8 }, (_, i) => {
      const el = document.createElementNS(SVG_NS, "circle");
      poolLayer.appendChild(el);
      return { el, angle: (i / 8) * Math.PI * 2, speed: 0.5 + Math.random() * 0.9, r: 18 + Math.random() * 20 };
    });

    const drops: Drop[] = [];
    const motes: Mote[] = [];
    let dripDebt = 0;
    let moteDebt = 0;
    let splash = 0;
    let presence = 0; // 0 hidden → 1 fully here
    let lift = 0; // the pool rises as it evaporates
    let edge = 0;
    let last = performance.now();
    let frame = 0;
    let wasDone = false;

    const spawnDrop = () => {
      const el = document.createElementNS(SVG_NS, "ellipse");
      dropsLayer.appendChild(el);
      const roll = Math.random();
      const side: Drop["side"] = roll < 0.18 ? -1 : roll < 0.36 ? 1 : 0;
      const rMax = side ? 7 + Math.random() * 5 : 9 + Math.random() * 11;
      const x = side === -1 ? FRAME * 0.5 : side === 1 ? width - FRAME * 0.5 : width * (0.05 + Math.random() * 0.9);
      const y = side ? height * (0.04 + Math.random() * 0.3) : 0;
      drops.push({ el, x, y, r: 0, rMax, vy: 0, t: 0, bead: 0.3 + Math.random() * 0.8, falling: false, side });
    };

    const spawnMote = (poolX: number, poolY: number, burst: boolean) => {
      const el = document.createElementNS(SVG_NS, "circle");
      el.setAttribute("fill", MOTE_COLOURS[Math.floor(Math.random() * MOTE_COLOURS.length)]);
      motesLayer.appendChild(el);
      const spread = burst ? 260 : 150;
      motes.push({
        el,
        x: poolX + (Math.random() - 0.5) * spread * 2,
        y: poolY - 6 - Math.random() * 14,
        vx: (Math.random() - 0.5) * (burst ? 60 : 22),
        vy: -(burst ? 160 + Math.random() * 260 : 30 + Math.random() * 70),
        life: burst ? 2.2 + Math.random() * 1.6 : 2.5 + Math.random() * 3,
        age: 0,
        r: 0.7 + Math.random() * (burst ? 2.6 : 1.8),
        phase: Math.random() * Math.PI * 2,
      });
    };

    const tick = (now: number) => {
      const dt = Math.min(0.05, (now - last) / 1000);
      last = now;
      const s = live.current;
      const poolX = width / 2;
      const here = PRESENT.includes(s.phase);
      const leaving = s.phase === "leaving";
      const poolY = height - POOL_LIFT - lift;

      presence += ((here ? 1 : 0) - presence) * Math.min(1, dt * (here ? 4.5 : 3));
      if (s.phase === "hidden") lift = 0;
      else if (leaving) lift += dt * 260;
      else lift = Math.max(0, lift - dt * 600);

      // The liquid clinging to the frame thickens with your voice.
      edge += ((here ? FRAME + s.level * 6 : 0) - edge) * Math.min(1, dt * 5);
      top.setAttribute("width", String(width));
      top.setAttribute("height", edge.toFixed(1));
      left.setAttribute("height", String(height));
      left.setAttribute("width", (edge * 0.7).toFixed(1));
      right.setAttribute("height", String(height));
      right.setAttribute("x", (width - edge * 0.7).toFixed(1));
      right.setAttribute("width", (edge * 0.7).toFixed(1));

      if (!reduced) {
        dripDebt += dripRate(s.phase, s.level) * dt;
        while (dripDebt >= 1 && drops.length < 34) {
          dripDebt -= 1;
          spawnDrop();
        }
        if (s.phase === "done" && !wasDone) for (let i = 0; i < 70; i++) spawnMote(poolX, poolY, true);
        moteDebt += moteRate(s.phase, s.level) * dt;
        while (moteDebt >= 1 && motes.length < 160) {
          moteDebt -= 1;
          spawnMote(poolX, poolY, false);
        }
      }
      wasDone = s.phase === "done";

      for (let i = drops.length - 1; i >= 0; i--) {
        const d = drops[i];
        if (!d.falling) {
          d.t += dt;
          const grow = Math.min(1, d.t / d.bead);
          d.r = d.rMax * (1 - (1 - grow) ** 3);
          if (!d.side) d.y = edge + d.r * 0.5;
          d.el.setAttribute("rx", (d.r * 0.92).toFixed(1));
          d.el.setAttribute("ry", (d.r * (1 + grow * 0.4)).toFixed(1));
          if (grow >= 1) {
            d.falling = true;
            d.vy = d.side ? 20 : 30;
          }
        } else if (d.side) {
          // Rivulets cling to the side of the screen: viscous, slow, long.
          d.vy = Math.min(220, d.vy + 260 * dt);
          d.y += d.vy * dt;
          d.el.setAttribute("rx", (d.r * 0.75).toFixed(1));
          d.el.setAttribute("ry", (d.r * (1.4 + d.vy / 110)).toFixed(1));
        } else {
          d.vy += 1100 * dt;
          d.y += d.vy * dt;
          const progress = Math.min(1, Math.max(0, d.y / poolY));
          // Drops curve toward the pool as they fall, like light pulled by gravity.
          d.x += (poolX - d.x) * Math.min(1, dt * 3.4 * progress * progress);
          const stretch = Math.min(1.7, d.vy / 620);
          d.el.setAttribute("rx", (d.r * (1 - stretch * 0.22)).toFixed(1));
          d.el.setAttribute("ry", (d.r * (1 + stretch)).toFixed(1));
        }
        d.el.setAttribute("cx", d.x.toFixed(1));
        d.el.setAttribute("cy", d.y.toFixed(1));
        const landed = !d.side && d.y >= poolY - 10;
        if (landed || d.y > height + 40) {
          if (landed && here) splash = Math.min(54, splash + d.r * 1.5);
          d.el.remove();
          drops.splice(i, 1);
        }
      }

      for (let i = motes.length - 1; i >= 0; i--) {
        const m = motes[i];
        m.age += dt;
        m.vy *= 1 - dt * 0.35;
        m.x += (m.vx + Math.sin(now / 900 + m.phase) * 14) * dt;
        m.y += m.vy * dt;
        const t = m.age / m.life;
        const twinkle = 0.55 + 0.45 * Math.sin(now / 160 + m.phase * 3);
        const fade = t < 0.15 ? t / 0.15 : 1 - (t - 0.15) / 0.85;
        m.el.setAttribute("cx", m.x.toFixed(1));
        m.el.setAttribute("cy", m.y.toFixed(1));
        m.el.setAttribute("r", (m.r * (0.6 + twinkle * 0.6)).toFixed(2));
        m.el.setAttribute("opacity", Math.max(0, fade * twinkle * presence).toFixed(2));
        if (t >= 1) {
          m.el.remove();
          motes.splice(i, 1);
        }
      }

      splash *= Math.pow(0.05, dt);
      const level = s.level;
      const busy = s.phase === "working" || s.phase === "thinking" || s.phase === "transcribing";
      const breathe = Math.sin(now / 650) * 6;
      const rx = (150 + level * 130 + splash * 1.7 + breathe) * presence;
      const ry = (24 + level * 26 + splash * 0.5) * presence;
      core.setAttribute("cx", poolX.toFixed(1));
      core.setAttribute("cy", poolY.toFixed(1));
      core.setAttribute("rx", Math.max(0, rx).toFixed(1));
      core.setAttribute("ry", Math.max(0, ry).toFixed(1));
      poolGradient.setAttribute("cx", poolX.toFixed(1));
      poolGradient.setAttribute("cy", (poolY - ry * 0.4).toFixed(1));
      poolGradient.setAttribute("r", Math.max(1, rx * 1.15).toFixed(1));
      // The pool's surface: a soft highlight and the light it casts below.
      shine.setAttribute("cx", (poolX - rx * 0.18).toFixed(1));
      shine.setAttribute("cy", (poolY - ry * 0.45).toFixed(1));
      shine.setAttribute("rx", Math.max(0, rx * 0.45).toFixed(1));
      shine.setAttribute("ry", Math.max(0, ry * 0.28).toFixed(1));
      floor.setAttribute("cx", poolX.toFixed(1));
      floor.setAttribute("cy", (poolY + ry * 1.6).toFixed(1));
      floor.setAttribute("rx", Math.max(0, rx * 1.9).toFixed(1));
      floor.setAttribute("ry", Math.max(0, ry * 1.4).toFixed(1));
      const spin = busy ? 2.8 : s.phase === "listening" ? 1.3 + level * 5 : 0.6;
      for (const b of blobs) {
        b.angle += b.speed * spin * dt;
        const bx = poolX + Math.cos(b.angle) * rx * 0.72;
        const by = poolY + Math.sin(b.angle * 1.7) * ry * 0.8 - level * 30 * Math.abs(Math.sin(b.angle * 2.3));
        const br = b.r * (0.55 + level * 1.2 + (busy ? 0.3 : 0)) * presence;
        b.el.setAttribute("cx", bx.toFixed(1));
        b.el.setAttribute("cy", by.toFixed(1));
        b.el.setAttribute("r", Math.max(0, br).toFixed(1));
      }
      frame = requestAnimationFrame(tick);
    };
    frame = requestAnimationFrame(tick);
    return () => {
      cancelAnimationFrame(frame);
      window.removeEventListener("resize", resize);
      dropsLayer.replaceChildren();
      poolLayer.replaceChildren();
      motesLayer.replaceChildren();
    };
  }, []);

  return (
    <svg ref={svgRef} className="liquid" aria-hidden="true" preserveAspectRatio="none">
      <defs>
        <linearGradient id="vico-drop" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0" stopColor="#b9a6ff" />
          <stop offset="0.5" stopColor="#7c5cff" />
          <stop offset="1" stopColor="#21d4fd" />
        </linearGradient>
        <linearGradient id="vico-frame" x1="0" y1="0" x2="1" y2="1">
          <stop offset="0" stopColor="#7c5cff" />
          <stop offset="0.35" stopColor="#21d4fd" />
          <stop offset="0.65" stopColor="#ff5ecf" />
          <stop offset="1" stopColor="#ffd38a" />
        </linearGradient>
        <radialGradient id="vico-pool" gradientUnits="userSpaceOnUse" cx="0" cy="0" r="1">
          <stop offset="0" stopColor="#fbf7ff" />
          <stop offset="0.28" stopColor="#c8b8ff" />
          <stop offset="0.55" stopColor="#7c5cff" />
          <stop offset="0.8" stopColor="#21d4fd" />
          <stop offset="1" stopColor="#ff5ecf" />
        </radialGradient>
        <radialGradient id="vico-floor">
          <stop offset="0" stopColor="#8d74ff" stopOpacity="0.55" />
          <stop offset="0.5" stopColor="#21d4fd" stopOpacity="0.16" />
          <stop offset="1" stopColor="#21d4fd" stopOpacity="0" />
        </radialGradient>
        <filter id="vico-goo" x="-10%" y="-10%" width="120%" height="120%">
          <feGaussianBlur in="SourceGraphic" stdDeviation="6" result="blur" />
          <feColorMatrix in="blur" mode="matrix" values="1 0 0 0 0  0 1 0 0 0  0 0 1 0 0  0 0 0 20 -7" result="goo" />
          <feGaussianBlur in="goo" stdDeviation="18" result="glow" />
          <feMerge>
            <feMergeNode in="glow" />
            <feMergeNode in="glow" />
            <feMergeNode in="goo" />
          </feMerge>
        </filter>
        <filter id="vico-soft" x="-50%" y="-50%" width="200%" height="200%">
          <feGaussianBlur stdDeviation="6" />
        </filter>
        <filter id="vico-sparkle" x="-200%" y="-200%" width="500%" height="500%">
          <feGaussianBlur stdDeviation="1.4" result="b" />
          <feMerge>
            <feMergeNode in="b" />
            <feMergeNode in="SourceGraphic" />
          </feMerge>
        </filter>
      </defs>
      <ellipse data-layer="floor" fill="url(#vico-floor)" />
      <g filter="url(#vico-goo)">
        <g fill="url(#vico-frame)">
          <rect data-edge="top" x="0" y="0" width="0" height="0" />
          <rect data-edge="left" x="0" y="0" width="0" height="0" />
          <rect data-edge="right" x="0" y="0" width="0" height="0" />
        </g>
        <g data-layer="drops" fill="url(#vico-drop)" />
        <g data-layer="pool" fill="url(#vico-pool)" />
      </g>
      <ellipse data-layer="shine" fill="#ffffff" opacity="0.55" filter="url(#vico-soft)" />
      <g data-layer="motes" filter="url(#vico-sparkle)" />
    </svg>
  );
}

function formatClock(seconds: number): string {
  const s = Math.max(0, Math.ceil(seconds));
  if (s >= 3600) return `${Math.floor(s / 3600)}h ${String(Math.floor((s % 3600) / 60)).padStart(2, "0")}m`;
  return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`;
}

/** The pool turns to frost and counts down while the free key rests. */
function Frost({ until }: { until: number }) {
  const [now, setNow] = useState(Date.now());
  const total = useRef(Math.max(1, (until - Date.now()) / 1000));
  useEffect(() => {
    const id = window.setInterval(() => setNow(Date.now()), 250);
    return () => window.clearInterval(id);
  }, []);
  const left = Math.max(0, (until - now) / 1000);
  const fraction = left / total.current;
  return (
    <div className="frost" role="timer" aria-label={`Resuming in ${formatClock(left)}`} data-testid="cooldown">
      <svg viewBox="0 0 120 120" aria-hidden="true">
        <circle cx="60" cy="60" r="52" className="frost-track" />
        <circle
          cx="60"
          cy="60"
          r="52"
          className="frost-fill"
          strokeDasharray={326.7}
          strokeDashoffset={326.7 * (1 - fraction)}
          transform="rotate(-90 60 60)"
        />
      </svg>
      <span>{formatClock(left)}</span>
    </div>
  );
}

function rimMode(phase: Phase): string {
  switch (phase) {
    case "working":
    case "thinking":
    case "transcribing":
      return "comet";
    case "cooling":
      return "ice";
    case "done":
      return "flare";
    case "error":
      return "ember";
    case "listening":
      return "breathe listening";
    default:
      return "breathe";
  }
}

export function Aura({ session }: { session: Session }) {
  const { phase } = session;
  const promptOwnsText = PROMPT_PHASES.includes(phase);
  const deep = phase === "setup" || phase === "settings";
  const result = phase === "done" || phase === "error";
  const mode = rimMode(phase);
  return (
    <div
      className={`aura phase-${phase} ${deep ? "deep" : ""}`}
      style={{ ["--level" as string]: session.level.toFixed(3) }}
      data-testid="aura"
      aria-hidden={phase === "hidden"}
    >
      <div className="veil" />
      <div className="aurora" aria-hidden="true">
        <i className="a1" />
        <i className="a2" />
        <i className="a3" />
        <i className="a4" />
      </div>
      <div className={`rim ${mode}`} />
      <div className={`rim bloom ${mode}`} />
      {phase === "done" && <div className="heaven" key="heaven" />}
      <Liquid session={session} />
      {phase === "cooling" && session.cooldownUntil && <Frost until={session.cooldownUntil} />}
      <div className="narration" role="status" aria-live="polite">
        {result ? (
          <div className={`result ${phase}`} key={`${phase}-${session.message}`} data-testid="result">
            {session.localized && <p className="echo">{session.localized}</p>}
            <p>{session.message}</p>
          </div>
        ) : (
          !promptOwnsText &&
          session.narration && (
            <p className="line" key={session.narration} data-testid="narration">
              {session.narration}
            </p>
          )
        )}
      </div>
    </div>
  );
}
