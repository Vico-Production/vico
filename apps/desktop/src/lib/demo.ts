// A scripted stand-in engine for the browser preview (?demo=1). Nothing here touches the
// computer: it only replays a realistic task so the visuals can be seen end to end.
import type { Envelope, Run, Step } from "./contracts";

type Method = "GET" | "POST" | "PUT" | "DELETE";

const ok = (data: unknown): Envelope<unknown> => ({ api_version: "1", ok: true, data, error: null });

function step(id: string, effect: string, outcome: Step["outcome"], status: Step["status"]): Step {
  return {
    id, tool: "browser_open", arguments: {}, explanation: "", effect, targets: [], outcome,
    reason: outcome === "confirm_required" ? "This may send, post or submit something, so Vico always asks first." : "",
    content_upload: false, approval: "pending", status, message: "", verification: "", verified: false, data: {},
  };
}

export function demoTransport() {
  let started = 0;
  let decided = 0;
  let recordingSince = 0;
  const settings = { onboarding_complete: true, cloud_consent: true, require_approval: true,
    allow_send_without_approval: false, workspace: "~/Documents/VicoDemo", allowed_roots: ["~"],
    stt_provider: "gemini", llm_provider: "gemini", fallback_consent: true, stt_model: null, llm_model: null,
    daily_request_budget: 500, max_steps: 12, browser_channel: "auto", speech_server_url: null, voice_replies: true, wake_word: false,
    look: "peek" as string };
  // ?first=1 starts at first-run setup; ?look=possession|yoyo|peek picks a look.
  const params = new URLSearchParams(window.location.search);
  if (params.has("first")) settings.onboarding_complete = false;
  if (params.get("look")) settings.look = params.get("look") as string;
  const text = "Open BBC News and read me the top headline";

  const run = (): Run => {
    const t = (Date.now() - started) / 1000;
    const base: Run = { id: "demo", state: "normalizing", mode: "cloud", language: "en", text, original: text,
      canonical: text, steps: [], pending_step_id: null, question: null, message: null, message_localized: null,
      error: null, cooldown_until: null, timeline: [] };
    const first = step("s1", "Open bbc.com/news in Vico's browser window", "approval_required", "awaiting_approval");
    if (t < 1.2) return base;
    if (t < 2.6) return { ...base, state: "planning" };
    if (!decided) return { ...base, state: "awaiting_approval", steps: [first], pending_step_id: "s1" };
    const d = (Date.now() - decided) / 1000;
    const done1 = { ...first, status: "succeeded" as const, approval: "approved" as const };
    if (d < 2.4) return { ...base, state: "executing", steps: [done1] };
    if (d < 3.2) return { ...base, state: "verifying", steps: [done1] };
    if (d < 7.6) {
      return { ...base, state: "cooling_down", steps: [done1],
        cooldown_until: new Date(decided + 7600).toISOString() };
    }
    const read = step("s2", "Read the text of bbc.com/news", "allowed", "running");
    if (d < 9.8) return { ...base, state: "executing", steps: [done1, read] };
    return { ...base, state: "completed", steps: [done1, { ...read, status: "succeeded" }],
      message: "BBC News is open. The top headline is shown at the top of the page." };
  };

  return async (method: Method, path: string, body?: unknown): Promise<Envelope<unknown>> => {
    await new Promise((r) => setTimeout(r, 60));
    if (path === "/settings" && method === "PUT") Object.assign(settings, body);
    if (path === "/settings") return ok(settings);
    if (path === "/health") {
      const provider = { status: "ready", configured: true, requests_today: 3, daily_budget: 500,
        audio_seconds_today: 0, rate_limited: false, cooldown_s: 0 };
      return ok({ version: "demo", platform: "browser", adapter: "demo", online: true, cloud_ready: true,
        speech_ready: true, voice_ready: false, cloud_consent: true, providers: { gemini: provider, groq: provider, speech_server: provider },
        recording: false, browser_open: false });
    }
    if (path === "/secrets") return ok({ gemini: true, groq: false });
    if (path === "/audio/start") {
      recordingSince = Date.now();
      return ok({ recording: true, elapsed_s: 0, max_s: 15, level: 0, full: false });
    }
    if (path === "/audio/status") {
      const e = (Date.now() - recordingSince) / 1000;
      // A spoken sentence: rises, wavers, falls silent after ~2.6 s.
      const level = e < 0.4 || e > 2.6 ? 0.01 : 0.25 + 0.45 * Math.abs(Math.sin(e * 7)) * Math.abs(Math.sin(e * 2.3));
      return ok({ recording: true, elapsed_s: e, max_s: 15, level, full: false });
    }
    if (path === "/audio/stop") {
      return ok({ seconds: 2.6, transcript: { text, language: "en", provider: "gemini", model: "gemini-3.6-flash",
        latency_ms: 640, confidence: null } });
    }
    if (path === "/audio/cancel") return ok({ recording: false });
    if (path === "/agent/runs" && method === "POST") {
      started = Date.now();
      decided = 0;
      return ok(run());
    }
    if (path.endsWith("/decision")) {
      decided = Date.now();
      return ok(run());
    }
    if (path.endsWith("/cancel")) return ok({ ...run(), state: "cancelled", message: "Stopped." });
    if (path.startsWith("/agent/runs/")) return ok(run());
    return ok({});
  };
}
