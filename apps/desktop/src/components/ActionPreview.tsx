import { useEffect, useRef, useState } from "react";
import type { Step } from "../lib/contracts";

export function ActionPreview({
  step,
  onApprove,
  onReject,
  busy,
}: {
  step: Step;
  onApprove: (confirm: boolean) => void;
  onReject: () => void;
  busy: boolean;
}) {
  const [confirmed, setConfirmed] = useState(false);
  const needsConfirm = step.outcome === "confirm_required";
  const approveRef = useRef<HTMLButtonElement>(null);
  const boxRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    setConfirmed(false);
    (needsConfirm ? boxRef.current : approveRef.current)?.focus();
  }, [step.id, needsConfirm]);

  return (
    <section
      className={`card approval ${needsConfirm ? "danger" : ""}`}
      aria-labelledby="approval-title"
      data-testid="approval-card"
    >
      <h3 id="approval-title">{needsConfirm ? "Confirm this step" : "Approve this step?"}</h3>
      <p className="effect" data-testid="approval-effect">
        {step.effect}
      </p>
      {step.explanation && <p className="muted">Why: {step.explanation}</p>}
      {step.targets.length > 0 && (
        <ul className="targets" aria-label="Affected locations">
          {step.targets.map((t) => (
            <li key={t}>
              <code>{t}</code>
            </li>
          ))}
        </ul>
      )}
      <details>
        <summary>Technical details</summary>
        <p>
          Tool <code>{step.tool}</code>
        </p>
        <pre>{JSON.stringify(step.arguments, null, 2)}</pre>
        <p className="muted">{step.reason}</p>
      </details>
      {step.content_upload && (
        <p className="warn-text">This sends the file's text to your cloud provider.</p>
      )}
      {needsConfirm && (
        <label className="confirm-box">
          <input
            ref={boxRef}
            type="checkbox"
            checked={confirmed}
            onChange={(e) => setConfirmed(e.target.checked)}
            data-testid="confirm-checkbox"
          />
          <span>{step.reason} I have checked it and want to go ahead.</span>
        </label>
      )}
      <div className="row">
        <button
          ref={approveRef}
          className={`btn ${needsConfirm ? "danger" : "primary"}`}
          disabled={busy || (needsConfirm && !confirmed)}
          onClick={() => onApprove(confirmed)}
          data-testid="approve-button"
        >
          {needsConfirm ? "Confirm and run" : "Approve"}
        </button>
        <button className="btn" disabled={busy} onClick={onReject} data-testid="reject-button">
          Reject
        </button>
      </div>
    </section>
  );
}
