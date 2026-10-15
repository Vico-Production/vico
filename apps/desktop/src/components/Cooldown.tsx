import { useEffect, useRef, useState } from "react";

function format(seconds: number): string {
  const s = Math.max(0, Math.ceil(seconds));
  if (s >= 3600) {
    const h = Math.floor(s / 3600);
    const m = Math.floor((s % 3600) / 60);
    return `${h}h ${m.toString().padStart(2, "0")}m`;
  }
  return `${Math.floor(s / 60)}:${(s % 60).toString().padStart(2, "0")}`;
}

/** Seconds left until `deadline` (ms since epoch), ticking 4 times a second. */
function useRemaining(deadline: number | null): number {
  const [now, setNow] = useState(Date.now());
  useEffect(() => {
    if (deadline === null) return;
    const id = window.setInterval(() => setNow(Date.now()), 250);
    return () => window.clearInterval(id);
  }, [deadline]);
  return deadline === null ? 0 : Math.max(0, (deadline - now) / 1000);
}

function Ring({ fraction, size = 22 }: { fraction: number; size?: number }) {
  const r = size / 2 - 3;
  const c = 2 * Math.PI * r;
  return (
    <svg className="cool-ring" width={size} height={size} viewBox={`0 0 ${size} ${size}`} aria-hidden="true">
      <circle cx={size / 2} cy={size / 2} r={r} className="track" />
      <circle
        cx={size / 2}
        cy={size / 2}
        r={r}
        className="fill"
        strokeDasharray={c}
        strokeDashoffset={c * (1 - fraction)}
        transform={`rotate(-90 ${size / 2} ${size / 2})`}
      />
    </svg>
  );
}

/** Inside a task: the key is cooling down and the task will continue by itself. */
export function CooldownNotice({ until }: { until: string }) {
  const deadline = Date.parse(until);
  const total = useRef(Math.max(1, (deadline - Date.now()) / 1000));
  const left = useRemaining(deadline);
  return (
    <div className="cooldown" role="status" aria-live="polite" data-testid="cooldown-notice">
      <Ring fraction={left / total.current} size={34} />
      <div>
        <strong>Your free AI key is cooling down · {format(left)}</strong>
        <small>Google limits how fast free keys can be used. Vico will carry on automatically.</small>
      </div>
    </div>
  );
}

/** Header chip shown while every free model is resting. */
export function CooldownChip({ seconds }: { seconds: number }) {
  const [deadline] = useState(() => Date.now() + seconds * 1000);
  const total = useRef(Math.max(1, seconds));
  const left = useRemaining(deadline);
  if (left <= 0) return null;
  return (
    <span className="status cooling" role="status" title="Your free Gemini key is resting. It will be ready again soon." data-testid="cooldown-chip">
      <Ring fraction={left / total.current} size={16} />
      Key cooling · {format(left)}
    </span>
  );
}
