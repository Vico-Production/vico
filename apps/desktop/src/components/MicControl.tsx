import type { AudioStatus } from "../lib/contracts";
import type { MicPhase } from "../lib/hooks";

const LABELS: Record<MicPhase, string> = {
  idle: "Start speaking",
  starting: "Opening microphone",
  listening: "Stop and transcribe",
  processing: "Transcribing",
};

export function MicControl({
  phase,
  status,
  onStart,
  onStop,
  onCancel,
  disabled,
  disabledReason,
}: {
  phase: MicPhase;
  status: AudioStatus | null;
  onStart: () => void;
  onStop: () => void;
  onCancel: () => void;
  disabled?: boolean;
  disabledReason?: string;
}) {
  const listening = phase === "listening";
  const busy = phase === "starting" || phase === "processing";
  const level = status?.level ?? 0;
  const remaining = status ? Math.max(0, Math.ceil(status.max_s - status.elapsed_s)) : null;
  return (
    <div className="mic">
      <button
        className={`orb ${phase}`}
        style={{ ["--level" as string]: level.toFixed(2) }}
        onClick={listening ? onStop : onStart}
        disabled={disabled || busy}
        aria-label={LABELS[phase]}
        aria-pressed={listening}
        data-testid="mic-button"
      >
        <svg viewBox="0 0 24 24" aria-hidden="true" width="34" height="34">
          {listening ? (
            <rect x="7" y="7" width="10" height="10" rx="2" fill="currentColor" />
          ) : (
            <path
              fill="currentColor"
              d="M12 15a3 3 0 0 0 3-3V6a3 3 0 1 0-6 0v6a3 3 0 0 0 3 3Zm5-3a5 5 0 0 1-10 0H5a7 7 0 0 0 6 6.92V21h2v-2.08A7 7 0 0 0 19 12h-2Z"
            />
          )}
        </svg>
      </button>
      <div className="mic-text" aria-live="polite">
        <strong>{LABELS[phase]}</strong>
        {listening && <small>Listening… {remaining}s left (max 15s)</small>}
        {phase === "idle" && <small>{disabled && disabledReason ? disabledReason : "Push to talk. Vico never listens in the background."}</small>}
        {phase === "processing" && <small>Sending the clip to the speech provider</small>}
      </div>
      {listening && (
        <button className="btn ghost" onClick={onCancel} data-testid="mic-cancel">
          Discard
        </button>
      )}
    </div>
  );
}
