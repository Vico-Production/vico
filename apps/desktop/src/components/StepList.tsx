import type { Step } from "../lib/contracts";

const STATUS: Record<Step["status"], string> = {
  proposed: "Proposed",
  awaiting_approval: "Waiting for you",
  running: "Running",
  succeeded: "Done · verified",
  unverified: "Done · not verified",
  failed: "Failed",
  denied: "Blocked",
  rejected: "Declined",
};

export function StepList({ steps }: { steps: Step[] }) {
  if (!steps.length) return null;
  return (
    <ol className="steps" aria-label="Steps" data-testid="step-list">
      {steps.map((step, i) => (
        <li key={step.id} className={`step ${step.status}`}>
          <div className="step-head">
            <span className="step-num">{i + 1}</span>
            <span className="step-effect">{step.effect || step.explanation || step.tool}</span>
            <span className={`badge ${step.status}`}>{STATUS[step.status]}</span>
          </div>
          {step.message && <p className="step-msg">{step.message}</p>}
          {step.verification && step.status !== "denied" && <p className="muted small">Check: {step.verification}</p>}
          {typeof step.data.output === "string" && step.data.output && <pre className="output">{step.data.output}</pre>}
          {typeof step.data.text === "string" && step.data.text && <pre className="output">{step.data.text}</pre>}
        </li>
      ))}
    </ol>
  );
}
