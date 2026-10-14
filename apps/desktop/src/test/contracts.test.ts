import { readFileSync, readdirSync } from "node:fs";
import { join } from "node:path";
import { LANGUAGES, TERMINAL_STATES, type Health, type Run, type Settings, type Step } from "../lib/contracts";

const DIR = join(__dirname, "../../../../tests/fixtures/contracts");
const load = (name: string) => JSON.parse(readFileSync(join(DIR, name), "utf-8"));

// Record<keyof T, true> fails to compile if a key is added to or removed from the type.
const RUN_KEYS: Record<keyof Run, true> = {
  id: true, state: true, mode: true, language: true, text: true, original: true, canonical: true, steps: true,
  pending_step_id: true, question: true, message: true, message_localized: true, error: true, timeline: true,
};
const STEP_KEYS: Record<keyof Step, true> = {
  id: true, tool: true, arguments: true, explanation: true, effect: true, targets: true, outcome: true, reason: true,
  content_upload: true, approval: true, status: true, message: true, verification: true, verified: true, data: true,
};
const SETTINGS_KEYS: Record<keyof Settings, true> = {
  onboarding_complete: true, language: true, interpreter_source: true, interpreter_target: true, cloud_consent: true,
  require_approval: true, allow_send_without_approval: true, workspace: true, allowed_roots: true, stt_provider: true,
  llm_provider: true, fallback_consent: true, stt_model: true, llm_model: true, daily_request_budget: true,
  max_steps: true, browser_channel: true,
};
const HEALTH_KEYS: Record<keyof Health, true> = {
  version: true, platform: true, adapter: true, online: true, cloud_ready: true, speech_ready: true,
  cloud_consent: true, providers: true, recording: true, browser_open: true,
};

const sorted = (o: object) => Object.keys(o).sort();

describe("contract fixtures shared with Python", () => {
  it("are all valid envelopes", () => {
    for (const name of readdirSync(DIR)) {
      const env = load(name);
      expect(env.api_version).toBe("1");
      expect(env.ok).toBe(env.error === null);
    }
  });

  it("run and step shapes match the TypeScript types", () => {
    const run = load("run_awaiting_approval.json").data;
    expect(sorted(run)).toEqual(sorted(RUN_KEYS));
    expect(sorted(run.steps[0])).toEqual(sorted(STEP_KEYS));
    expect(LANGUAGES).toContain(run.language);
    expect(TERMINAL_STATES).not.toContain(run.state);
  });

  it("settings and health shapes match", () => {
    expect(sorted(load("settings.json").data)).toEqual(sorted(SETTINGS_KEYS));
    expect(sorted(load("health.json").data)).toEqual(sorted(HEALTH_KEYS));
  });

  it("error envelope carries a code and message", () => {
    const env = load("error_policy_denied.json");
    expect(env.error.code).toBe("policy_denied");
    expect(typeof env.error.message).toBe("string");
  });
});
