import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { setTransport } from "../lib/api";
import type { Envelope, Health, Run, Settings, Step } from "../lib/contracts";
import App from "../App";

const settings: Settings = {
  onboarding_complete: true,
  language: "en",
  interpreter_source: "en",
  interpreter_target: "yo",
  cloud_consent: true,
  require_approval: true,
  allow_send_without_approval: false,
  workspace: "C:/Users/demo/Documents/VicoDemo",
  allowed_roots: ["~"],
  stt_provider: "gemini",
  llm_provider: "gemini",
  fallback_consent: false,
  stt_model: null,
  llm_model: null,
  daily_request_budget: 500,
  max_steps: 12,
  browser_channel: "auto",
};

const provider = { status: "ready" as const, configured: true, requests_today: 0, daily_budget: 500, audio_seconds_today: 0, rate_limited: false, cooldown_s: 0 };

function health(online = true): Health {
  return {
    version: "0.1.0", platform: "win32", adapter: "windows", online, cloud_ready: online, speech_ready: online,
    cloud_consent: true, providers: { groq: provider, gemini: { ...provider, configured: false, status: "not_configured" } },
    recording: false, browser_open: false,
  };
}

function step(over: Partial<Step> = {}): Step {
  return {
    id: "s1", tool: "create_folder", arguments: { path: "Demo" }, explanation: "make it",
    effect: "Create the folder ~/Documents/VicoDemo/Demo", targets: ["C:/Users/demo/Documents/VicoDemo/Demo"],
    outcome: "approval_required", reason: "Approval is switched on.", content_upload: false, approval: "pending",
    status: "awaiting_approval", message: "", verification: "", verified: false, data: {}, ...over,
  };
}

function run(over: Partial<Run> = {}): Run {
  return {
    id: "r1", state: "awaiting_approval", mode: "cloud", language: "en", text: "make Demo", original: "make Demo",
    canonical: "make Demo", steps: [step()], pending_step_id: "s1", question: null, message: null,
    message_localized: null, error: null, cooldown_until: null, timeline: [], ...over,
  };
}

type Call = { method: string; path: string; body?: unknown };

function serve(routes: (call: Call) => unknown) {
  const calls: Call[] = [];
  setTransport(async (method, path, body) => {
    const call = { method, path, body };
    calls.push(call);
    const data = routes(call);
    if (data instanceof Error) {
      return { api_version: "1", ok: false, data: null, error: { code: "policy_denied", message: data.message, retryable: false, retry_after_s: null } };
    }
    return { api_version: "1", ok: true, data, error: null } as Envelope<unknown>;
  });
  return calls;
}

function baseRoutes(call: Call, extra?: (c: Call) => unknown) {
  const handled = extra?.(call);
  if (handled !== undefined) return handled;
  if (call.path === "/settings") return settings;
  if (call.path === "/languages") return [{ code: "en", name: "English", text_label: "untested", text_accuracy: null, speech_label: "untested", speech_accuracy: null, samples: { text: 0, speech: 0 }, note: "", experimental: false }];
  if (call.path === "/health") return health();
  if (call.path === "/history") return [];
  return {};
}

describe("Agent Mode", () => {
  it("shows the exact effect and only approves through the button", async () => {
    let current = run();
    const calls = serve((c) =>
      baseRoutes(c, (call) => {
        if (call.path === "/agent/runs" && call.method === "POST") return current;
        if (call.path === "/agent/runs/r1/decision") {
          current = run({ state: "executing", pending_step_id: null, steps: [step({ status: "running", approval: "approved" })] });
          return current;
        }
        if (call.path === "/agent/runs/r1") return current;
        return undefined;
      }),
    );
    render(<App />);
    const input = await screen.findByTestId("request-input");
    fireEvent.change(input, { target: { value: "make Demo" } });
    fireEvent.click(screen.getByTestId("run-button"));
    expect(await screen.findByTestId("approval-effect")).toHaveTextContent("Create the folder ~/Documents/VicoDemo/Demo");
    expect(document.querySelector(".tl.completed")).toBeNull();
    expect(screen.queryByText("Done · verified")).not.toBeInTheDocument();
    fireEvent.click(screen.getByTestId("approve-button"));
    await waitFor(() => expect(calls.some((c) => c.path === "/agent/runs/r1/decision")).toBe(true));
    expect(calls.find((c) => c.path === "/agent/runs/r1/decision")?.body).toEqual({ step_id: "s1", approved: true, confirm: false });
  });

  it("requires the confirmation box for confirm-only steps", async () => {
    const current = run({ steps: [step({ tool: "delete_path", outcome: "confirm_required", reason: "Deleting always needs confirmation." })] });
    serve((c) => baseRoutes(c, (call) => (call.path.startsWith("/agent/runs") ? current : undefined)));
    render(<App />);
    fireEvent.change(await screen.findByTestId("request-input"), { target: { value: "delete old" } });
    fireEvent.click(screen.getByTestId("run-button"));
    const approve = await screen.findByTestId("approve-button");
    expect(approve).toBeDisabled();
    fireEvent.click(screen.getByTestId("confirm-checkbox"));
    expect(approve).toBeEnabled();
  });

  it("does not show Done until the run is completed and verified", async () => {
    const done = run({
      state: "completed", pending_step_id: null, message: "Created Demo.",
      steps: [step({ status: "succeeded", approval: "approved", verified: true, message: "Created Demo.", verification: "Folder exists on disk." })],
    });
    serve((c) => baseRoutes(c, (call) => (call.path.startsWith("/agent/runs") ? done : undefined)));
    render(<App />);
    fireEvent.change(await screen.findByTestId("request-input"), { target: { value: "make Demo" } });
    fireEvent.click(screen.getByTestId("run-button"));
    expect(await screen.findByText("Done · verified")).toBeInTheDocument();
    expect(screen.getAllByText("Created Demo.").length).toBeGreaterThan(0);
  });

  it("offline: the microphone is disabled but typing still works", async () => {
    serve((c) => baseRoutes(c, (call) => (call.path === "/health" ? health(false) : undefined)));
    render(<App />);
    await act(async () => {
      await new Promise((r) => setTimeout(r, 50));
    });
    expect(await screen.findByTestId("status-badge")).toHaveTextContent("Offline");
    expect(screen.getByTestId("mic-button")).toBeDisabled();
    expect(screen.getByTestId("request-input")).toBeEnabled();
  });

  it("shows a recoverable error when the engine is down", async () => {
    setTransport(async () => ({
      api_version: "1", ok: false, data: null,
      error: { code: "sidecar_unavailable", message: "The Vico engine is not running.", retryable: true, retry_after_s: null },
    }));
    render(<App />);
    expect(await screen.findByText(/did not start/)).toBeInTheDocument();
    expect(screen.getByText("Try again")).toBeInTheDocument();
  });
});

describe("Cooldown", () => {
  it("shows a countdown while the key cools and the task waits", async () => {
    const until = new Date(Date.now() + 30_000).toISOString();
    const cooling = run({ state: "cooling_down", steps: [], pending_step_id: null, cooldown_until: until });
    serve((c) =>
      baseRoutes(c, (call) => {
        if (call.path === "/health") {
          const h = health();
          return { ...h, providers: { ...h.providers, gemini: { ...h.providers.gemini, cooldown_s: 30 } } };
        }
        return call.path.startsWith("/agent/runs") ? cooling : undefined;
      }),
    );
    render(<App />);
    fireEvent.change(await screen.findByTestId("request-input"), { target: { value: "long task" } });
    fireEvent.click(screen.getByTestId("run-button"));
    expect(await screen.findByTestId("cooldown-notice")).toHaveTextContent(/cooling down · 0:(29|30)/);
    expect(screen.getByTestId("cooldown-notice")).toHaveTextContent("carry on automatically");
    expect(await screen.findByTestId("cooldown-chip")).toHaveTextContent("Key cooling");
  });
});

describe("History", () => {
  it("asks before clearing", async () => {
    let items = [{ id: 1, created_at: new Date().toISOString(), language: "en", summary: "Create Demo", tool: "create_folder", approval: "approved", outcome: "succeeded", verified: true, detail: null }];
    const calls = serve((c) =>
      baseRoutes(c, (call) => {
        if (call.path === "/history" && call.method === "DELETE") {
          items = [];
          return { deleted: 1 };
        }
        if (call.path === "/history") return items;
        return undefined;
      }),
    );
    render(<App />);
    fireEvent.click(await screen.findByTestId("open-history"));
    fireEvent.click(await screen.findByTestId("clear-history"));
    expect(calls.some((c) => c.method === "DELETE")).toBe(false);
    fireEvent.click(screen.getByTestId("confirm-clear"));
    await waitFor(() => expect(screen.getByText("No activity yet.")).toBeInTheDocument());
  });
});

describe("Onboarding", () => {
  it("is shown on first launch", async () => {
    serve((c) => baseRoutes(c, (call) => (call.path === "/settings" ? { ...settings, onboarding_complete: false } : undefined)));
    render(<App />);
    expect(await screen.findByTestId("onboarding")).toBeInTheDocument();
  });
});
