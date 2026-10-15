import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { setTransport } from "../lib/api";
import type { Envelope, Health, Run, Settings, Step } from "../lib/contracts";
import { Stage } from "../views/Windows";

const settings: Settings = {
  onboarding_complete: true,
  cloud_consent: true,
  require_approval: true,
  allow_send_without_approval: false,
  workspace: "C:/Users/demo/Documents/VicoDemo",
  allowed_roots: ["~"],
  stt_provider: "gemini",
  llm_provider: "gemini",
  fallback_consent: true,
  stt_model: null,
  llm_model: null,
  daily_request_budget: 500,
  max_steps: 12,
  browser_channel: "auto",
  speech_server_url: null,
  voice_replies: true,
  wake_word: true,
  look: "peek",
  looks: ["peek"],
  rotate: false,
  spots: {},
};

const provider = { status: "ready" as const, configured: true, requests_today: 0, daily_budget: 500,
  audio_seconds_today: 0, rate_limited: false, cooldown_s: 0 };

function health(over: Partial<Health> = {}): Health {
  return { version: "0.1.0", platform: "win32", adapter: "windows", online: true, cloud_ready: true,
    speech_ready: false, voice_ready: false, cloud_consent: true, providers: { gemini: provider, groq: provider, speech_server: provider }, recording: false,
    browser_open: false, ...over };
}

function step(over: Partial<Step> = {}): Step {
  return { id: "s1", tool: "open_app", arguments: { name: "notepad" }, explanation: "", effect: "Start the app Notepad",
    targets: [], outcome: "approval_required", reason: "Approval is switched on.", content_upload: false,
    approval: "pending", status: "awaiting_approval", message: "", verification: "", verified: false, data: {}, stage: null,
    ...over };
}

function run(over: Partial<Run> = {}): Run {
  return { id: "r1", state: "awaiting_approval", mode: "cloud", language: "en", text: "open notepad",
    original: "open notepad", canonical: "open notepad", steps: [step()], pending_step_id: "s1", question: null,
    message: null, message_localized: null, error: null, cooldown_until: null, control: null, timeline: [], version: 0, ...over };
}

type Call = { method: string; path: string; body?: unknown };

function serve(handler: (call: Call) => unknown) {
  const calls: Call[] = [];
  setTransport(async (method, path, body) => {
    const call = { method, path, body };
    calls.push(call);
    const data = handler(call);
    return { api_version: "1", ok: true, data: data ?? {}, error: null } as Envelope<unknown>;
  });
  return calls;
}

function base(call: Call, extra: (c: Call) => unknown = () => undefined) {
  const handled = extra(call);
  if (handled !== undefined) return handled;
  if (call.path === "/settings") return settings;
  if (call.path === "/health") return health();
  if (call.path === "/secrets") return { gemini: false, groq: false };
  return undefined;
}

async function summonAndType(text: string) {
  fireEvent.click(await screen.findByTestId("summon"));
  const words = await screen.findByTestId("words");
  fireEvent.change(words, { target: { value: text } });
  fireEvent.keyDown(words, { key: "Enter" });
}

describe("Vico", () => {
  it("types a request, shows the exact effect and approves with Enter", async () => {
    let current = run();
    const calls = serve((c) =>
      base(c, (call) => {
        if (call.path === "/agent/runs" && call.method === "POST") return current;
        if (call.path.endsWith("/decision")) {
          current = run({ state: "executing", pending_step_id: null, steps: [step({ status: "running" })] });
          return current;
        }
        if (call.path.startsWith("/agent/runs/")) return current;
        return undefined;
      }),
    );
    render(<Stage />);
    await summonAndType("open notepad");
    expect(await screen.findByTestId("approval-effect")).toHaveTextContent("Start the app Notepad");
    expect(calls.find((c) => c.path === "/agent/runs")?.body).toEqual({ text: "open notepad", language: null });
    fireEvent.keyDown(window, { key: "Enter" });
    await waitFor(() => expect(calls.some((c) => c.path.endsWith("/decision"))).toBe(true));
    expect(calls.find((c) => c.path.endsWith("/decision"))?.body).toEqual({ step_id: "s1", approved: true, confirm: false });
    expect(await screen.findByTestId("narration")).toHaveTextContent("Start the app Notepad");
  });

  it("needs Enter held down for risky steps", async () => {
    const risky = run({ steps: [step({ tool: "delete_path", effect: "Delete the file ~/old.txt", outcome: "confirm_required" })] });
    const calls = serve((c) => base(c, (call) => (call.path.startsWith("/agent/runs") ? risky : undefined)));
    render(<Stage />);
    await summonAndType("delete old.txt");
    await screen.findByTestId("approval");
    fireEvent.keyDown(window, { key: "Enter" });
    fireEvent.keyUp(window, { key: "Enter" });
    await act(() => new Promise((r) => setTimeout(r, 300)));
    expect(calls.some((c) => c.path.endsWith("/decision"))).toBe(false);
    fireEvent.keyDown(window, { key: "Enter" });
    await waitFor(() => expect(calls.some((c) => c.path.endsWith("/decision"))).toBe(true), { timeout: 3000 });
    expect(calls.find((c) => c.path.endsWith("/decision"))?.body).toEqual({ step_id: "s1", approved: true, confirm: true });
  });

  it("asks once for a free access code on first run", async () => {
    const calls = serve((c) =>
      base(c, (call) => (call.path === "/settings" && call.method === "GET" ? { ...settings, onboarding_complete: false } : undefined)),
    );
    render(<Stage />);
    // First, pick how Vico appears; Continue without a pick explains why it waits.
    fireEvent.click(await screen.findByTestId("look-continue"));
    expect(await screen.findByRole("alert")).toHaveTextContent("Pick how I should appear");
    fireEvent.click(screen.getByTestId("look-yoyo"));
    expect(screen.getByTestId("look-yoyo")).toHaveAttribute("aria-checked", "true");
    fireEvent.click(screen.getByTestId("look-continue"));
    const code = await screen.findByTestId("gemini-code");
    fireEvent.change(code, { target: { value: "AIzaTestKey12345" } });
    serve((c) => {
      calls.push(c);
      if (c.path === "/secrets") return { gemini: true, groq: false };
      return base(c);
    });
    fireEvent.click(screen.getByTestId("save-setup"));
    await waitFor(() => expect(calls.some((c) => c.method === "PUT" && c.path === "/settings")).toBe(true));
    expect(calls.find((c) => c.path === "/secrets/gemini")?.body).toEqual({ api_key: "AIzaTestKey12345" });
    expect(calls.find((c) => c.method === "PUT" && c.path === "/settings")?.body).toMatchObject({
      cloud_consent: true, onboarding_complete: true, look: "yoyo", looks: ["yoyo"], rotate: false,
    });
    // The last card says only how to come back to settings, and stays until a key.
    const card = await screen.findByTestId("welcome");
    expect(card.textContent).toBe(
      "If you want to come back to these settings, ask Vico to OPEN ITS SETTINGS — by voice or by typing.");
    expect(card.querySelector("strong")?.textContent).toBe("OPEN ITS SETTINGS");
    expect(card.querySelectorAll("button, a, svg")).toHaveLength(0);
    fireEvent.keyDown(window, { key: "Enter" });
    await waitFor(() => expect(screen.getByTestId("aura").className).toContain("phase-hidden"), { timeout: 3000 });
  });

  it("takes turns between ticked looks, one per summon", async () => {
    let current = "peek";
    const calls = serve((c) =>
      base(c, (call) => {
        if (call.path === "/settings" && call.method === "GET") {
          return { ...settings, look: current, looks: ["peek", "swarm", "lens"], rotate: true };
        }
        if (call.path === "/settings" && call.method === "PUT") {
          current = (call.body as { look?: string }).look ?? current;
          return { ...settings, look: current, looks: ["peek", "swarm", "lens"], rotate: true };
        }
        return undefined;
      }),
    );
    render(<Stage />);
    fireEvent.click(await screen.findByTestId("summon"));
    await waitFor(() => expect(screen.getByTestId("aura").className).toContain("look-swarm"));
    expect(calls.find((c) => c.method === "PUT" && c.path === "/settings")?.body).toEqual({ look: "swarm" });
    fireEvent.keyDown(window, { key: "Escape" });
    await waitFor(() => expect(screen.getByTestId("aura").className).toContain("phase-hidden"), { timeout: 3000 });
    fireEvent.click(await screen.findByTestId("summon"));
    await waitFor(() => expect(screen.getByTestId("aura").className).toContain("look-lens"));
  });

  it("rotation needs two or more looks", async () => {
    serve((c) => base(c, (call) => (call.path === "/settings" && call.method === "GET"
      ? { ...settings, onboarding_complete: false } : undefined)));
    render(<Stage />);
    fireEvent.click(await screen.findByTestId("mode-rotate"));
    fireEvent.click(screen.getByTestId("look-runner"));
    fireEvent.click(screen.getByTestId("look-continue"));
    expect(await screen.findByRole("alert")).toHaveTextContent("at least two");
    fireEvent.click(screen.getByTestId("look-lens"));
    expect(screen.getByTestId("look-runner")).toHaveAttribute("aria-checked", "true");
    expect(screen.getByTestId("look-lens")).toHaveAttribute("aria-checked", "true");
    fireEvent.click(screen.getByTestId("look-continue"));
    expect(await screen.findByTestId("gemini-code")).toBeInTheDocument();
  });

  it("opens its settings only when asked", async () => {
    const asked = run({ state: "completed", steps: [], pending_step_id: null, message: "Opening my settings.",
      control: { action: "settings" } });
    serve((c) => base(c, (call) => (call.path.startsWith("/agent/runs") ? asked : undefined)));
    render(<Stage />);
    expect(screen.queryByText(/settings and access codes/i)).toBeNull();
    await summonAndType("open your settings");
    expect(await screen.findByTestId("setup")).toHaveTextContent("Settings");
  });

  it("Possession lights up the window being used and narrates on its edge", async () => {
    const thinking = run({ state: "planning", steps: [], pending_step_id: null });
    serve((c) => base(c, (call) => {
      if (call.path === "/settings") return { ...settings, look: "possession" };
      return call.path.startsWith("/agent/runs") ? thinking : undefined;
    }));
    render(<Stage />);
    await summonAndType("open notepad");
    await waitFor(() => expect(screen.getByTestId("narration")).toHaveTextContent("Vico · Thinking"));
    expect(screen.getByTestId("aura").className).toContain("look-possession");
    expect(document.querySelector(".possession")).not.toBeNull(); // framed around the stand-in window
  });

  it("changes the look from settings", async () => {
    const calls = serve((c) => base(c, (call) => (call.path === "/secrets" ? { gemini: true, groq: false } : undefined)));
    render(<Stage />);
    await screen.findByTestId("summon");
    act(() => {
      window.dispatchEvent(new KeyboardEvent("keydown", { key: "v", ctrlKey: true, altKey: true }));
    });
    // Open settings the way the tray does, by typing the settings phrase.
    const words = await screen.findByTestId("words");
    fireEvent.change(words, { target: { value: "vico settings" } });
    fireEvent.keyDown(words, { key: "Enter" });
    fireEvent.click(await screen.findByTestId("look-possession"));
    fireEvent.click(screen.getByTestId("save-setup"));
    await waitFor(() => expect(calls.find((c) => c.method === "PUT" && c.path === "/settings")?.body).toMatchObject({
      look: "possession" }));
    await waitFor(() => expect(screen.getByTestId("aura").className).toContain("look-possession"));
  });

  it("shows the cooling countdown while the free key rests", async () => {
    const cooling = run({ state: "cooling_down", steps: [], pending_step_id: null,
      cooldown_until: new Date(Date.now() + 30_000).toISOString() });
    serve((c) => base(c, (call) => (call.path.startsWith("/agent/runs") ? cooling : undefined)));
    render(<Stage />);
    await summonAndType("do a long task");
    expect(await screen.findByTestId("cooldown")).toHaveTextContent(/0:(29|30)/);
    expect(screen.getByTestId("narration")).toHaveTextContent("carry on by itself");
  });

  it("Escape cancels a running task and Vico leaves", async () => {
    const thinking = run({ state: "planning", steps: [], pending_step_id: null });
    const calls = serve((c) => base(c, (call) => (call.path.startsWith("/agent/runs") ? thinking : undefined)));
    render(<Stage />);
    await summonAndType("open notepad");
    await screen.findByTestId("narration");
    fireEvent.keyDown(window, { key: "Escape" });
    await waitFor(() => expect(calls.some((c) => c.path === "/agent/runs/r1/cancel")).toBe(true));
    await waitFor(() => expect(screen.getByTestId("aura").className).toContain("phase-hidden"), { timeout: 3000 });
  });

  it("listens, stops after silence, shows what it heard and goes on its own", async () => {
    let since = 0;
    const calls = serve((c) =>
      base(c, (call) => {
        if (call.path === "/health") return health({ speech_ready: true });
        if (call.path === "/audio/start") {
          since = Date.now();
          return { recording: true, elapsed_s: 0, max_s: 15, level: 0, full: false };
        }
        if (call.path === "/audio/status") {
          const e = (Date.now() - since) / 1000;
          return { recording: true, elapsed_s: e, max_s: 15, level: e < 0.6 ? 0.5 : 0.01, full: false };
        }
        if (call.path === "/audio/stop") {
          return { seconds: 1, transcript: { text: "Ṣí Notepad", language: "yo", provider: "gemini", model: "m",
            latency_ms: 300, confidence: null } };
        }
        if (call.path.startsWith("/agent/runs")) return run({ state: "planning", steps: [], pending_step_id: null });
        return undefined;
      }),
    );
    render(<Stage />);
    fireEvent.click(await screen.findByTestId("summon"));
    await waitFor(() => expect((screen.getByTestId("words") as HTMLTextAreaElement).value).toBe("Ṣí Notepad"), { timeout: 4000 });
    await waitFor(() => expect(calls.some((c) => c.path === "/agent/runs" && c.method === "POST")).toBe(true), { timeout: 4000 });
    expect(calls.find((c) => c.path === "/agent/runs")?.body).toEqual({ text: "Ṣí Notepad", language: null });
  });

  it("comes up listening; a keystroke or the button switches to typing", async () => {
    const calls = serve((c) =>
      base(c, (call) => {
        if (call.path === "/health") return health({ speech_ready: true });
        if (call.path === "/audio/status") return { recording: true, elapsed_s: 0.2, max_s: 15, level: 0, full: false };
        return undefined;
      }),
    );
    render(<Stage />);
    fireEvent.click(await screen.findByTestId("summon"));
    expect(await screen.findByTestId("voice-title")).toHaveTextContent("listening");
    expect(screen.queryByTestId("words")).toBeNull(); // voice first: no text box
    await waitFor(() => expect(calls.some((c) => c.path === "/audio/start")).toBe(true));
    fireEvent.keyDown(window, { key: "o" });
    await waitFor(() => expect(calls.some((c) => c.path === "/audio/cancel")).toBe(true));
    expect(screen.getByTestId("prompt").className).toContain("typing");
    expect((screen.getByTestId("words") as HTMLTextAreaElement).value).toBe("o");
    fireEvent.click(screen.getByTestId("talk-instead"));
    fireEvent.click(await screen.findByTestId("type-instead"));
    expect(await screen.findByTestId("words")).toBeInTheDocument();
  });

  it("answers a greeting and keeps listening for the request", async () => {
    let since = 0;
    let starts = 0;
    const greeting = run({ state: "completed", steps: [], pending_step_id: null, language: "pcm",
      message: "How far! What can I do for you?", control: { action: "greet" } });
    const calls = serve((c) =>
      base(c, (call) => {
        if (call.path === "/health") return health({ speech_ready: true });
        if (call.path === "/audio/start") {
          starts += 1;
          since = Date.now();
          return { recording: true, elapsed_s: 0, max_s: 15, level: 0, full: false };
        }
        if (call.path === "/audio/status") {
          const e = (Date.now() - since) / 1000;
          return { recording: true, elapsed_s: e, max_s: 15, level: starts === 1 && e < 0.5 ? 0.5 : 0.01, full: false };
        }
        if (call.path === "/audio/stop") {
          return { seconds: 1, transcript: { text: "how far", language: "pcm", provider: "gemini", model: "m",
            latency_ms: 300, confidence: null } };
        }
        if (call.path.startsWith("/agent/runs")) return greeting;
        return undefined;
      }),
    );
    render(<Stage />);
    fireEvent.click(await screen.findByTestId("summon"));
    expect(await screen.findByTestId("result", {}, { timeout: 6000 })).toHaveTextContent("How far!");
    // it does not leave: it listens again (without taking the keyboard) for what you want
    await waitFor(() => expect(starts).toBe(2), { timeout: 4000 });
    await waitFor(() => expect(screen.getByTestId("aura").className).toContain("phase-listening"));
    expect(calls.filter((c) => c.path === "/agent/runs" && c.method === "POST")).toHaveLength(1);
  }, 15000);
});
