import type { Run, RunState } from "../lib/contracts";

const STAGES = ["Heard", "Understood", "Proposed", "Approved", "Executing", "Verifying", "Done"];

const STAGE_INDEX: Record<RunState, number> = {
  idle: 0,
  normalizing: 0,
  planning: 1,
  awaiting_clarification: 1,
  cooling_down: 1,
  validating: 2,
  awaiting_approval: 2,
  executing: 4,
  verifying: 5,
  completed: 6,
  failed: 6,
  cancelled: 6,
};

const TERMINAL_LABEL: Partial<Record<RunState, string>> = {
  completed: "Done",
  failed: "Failed",
  cancelled: "Cancelled",
};

export function Timeline({ run }: { run: Run }) {
  const index = STAGE_INDEX[run.state];
  const terminal = TERMINAL_LABEL[run.state];
  return (
    <ol className="timeline" aria-label="Progress" data-testid="timeline">
      {STAGES.map((stage, i) => {
        const label = i === STAGES.length - 1 && terminal ? terminal : stage;
        const state = i < index ? "done" : i === index ? (terminal ? run.state : "current") : "todo";
        return (
          <li key={stage} className={`tl ${state}`} aria-current={state === "current" ? "step" : undefined}>
            <span className="dot" aria-hidden="true" />
            <span>{label}</span>
          </li>
        );
      })}
    </ol>
  );
}
