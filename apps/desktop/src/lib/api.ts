// All sidecar calls go through the Tauri `api_request` command, so the per-launch token
// stays in the Rust process and never reaches this JavaScript.
import type {
  ApiError,
  AudioStatus,
  Envelope,
  Health,
  HistoryEntry,
  Language,
  LanguageCapability,
  Run,
  Settings,
  Transcript,
} from "./contracts";

type Method = "GET" | "POST" | "PUT" | "DELETE";

export class VicoApiError extends Error {
  constructor(public readonly error: ApiError) {
    super(error.message);
  }
  get code() {
    return this.error.code;
  }
}

type Transport = (method: Method, path: string, body?: unknown) => Promise<Envelope<unknown>>;

function isTauri(): boolean {
  return typeof window !== "undefined" && "__TAURI_INTERNALS__" in window;
}

const tauriTransport: Transport = async (method, path, body) => {
  const { invoke } = await import("@tauri-apps/api/core");
  return invoke<Envelope<unknown>>("api_request", { method, path, body: body ?? null });
};

// Browser-only development: `npm run dev` against a sidecar started by scripts/dev_sidecar.
const devTransport: Transport = async (method, path, body) => {
  const base = import.meta.env.VITE_SIDECAR_URL as string | undefined;
  const token = import.meta.env.VITE_SIDECAR_TOKEN as string | undefined;
  if (!base || !token) {
    return unavailable("Run Vico from the desktop app (npm run tauri dev).");
  }
  try {
    const res = await fetch(`${base}/api/v1${path}`, {
      method,
      headers: { Authorization: `Bearer ${token}`, "Content-Type": "application/json" },
      body: body === undefined ? undefined : JSON.stringify(body),
    });
    return (await res.json()) as Envelope<unknown>;
  } catch {
    return unavailable("The Vico engine is not running.");
  }
};

function unavailable(message: string): Envelope<unknown> {
  return {
    api_version: "1",
    ok: false,
    data: null,
    error: { code: "sidecar_unavailable", message, retryable: true, retry_after_s: null },
  };
}

let transport: Transport = isTauri() ? tauriTransport : devTransport;

export function setTransport(t: Transport) {
  transport = t;
}

async function call<T>(method: Method, path: string, body?: unknown): Promise<T> {
  let envelope: Envelope<unknown>;
  try {
    envelope = await transport(method, path, body);
  } catch (err) {
    envelope = unavailable(typeof err === "string" ? err : "The Vico engine is not responding.");
  }
  if (!envelope.ok || envelope.error) {
    throw new VicoApiError(
      envelope.error ?? { code: "internal", message: "Unknown error", retryable: false, retry_after_s: null },
    );
  }
  return envelope.data as T;
}

export const api = {
  health: () => call<Health>("GET", "/health"),
  settings: () => call<Settings>("GET", "/settings"),
  updateSettings: (patch: Partial<Settings>) => call<Settings>("PUT", "/settings", patch),
  languages: () => call<LanguageCapability[]>("GET", "/languages"),
  secrets: () => call<Record<string, boolean>>("GET", "/secrets"),
  saveSecret: (provider: string, apiKey: string) =>
    call<{ provider: string; configured: boolean }>("PUT", `/secrets/${provider}`, { api_key: apiKey }),
  deleteSecret: (provider: string) => call<{ provider: string; configured: boolean }>("DELETE", `/secrets/${provider}`),
  models: (provider: string) => call<{ provider: string; models: string[] }>("GET", `/providers/${provider}/models`),

  startRun: (text: string, language?: Language) => call<Run>("POST", "/agent/runs", { text, language: language ?? null }),
  currentRun: () => call<Run | null>("GET", "/agent/runs/current"),
  getRun: (id: string) => call<Run>("GET", `/agent/runs/${id}`),
  decide: (id: string, stepId: string, approved: boolean, confirm = false) =>
    call<Run>("POST", `/agent/runs/${id}/decision`, { step_id: stepId, approved, confirm }),
  reply: (id: string, answer: string) => call<Run>("POST", `/agent/runs/${id}/reply`, { answer }),
  cancel: (id: string) => call<Run>("POST", `/agent/runs/${id}/cancel`),

  startRecording: (language?: Language) => call<AudioStatus>("POST", "/audio/start", { language: language ?? null }),
  recordingStatus: () => call<AudioStatus>("GET", "/audio/status"),
  stopRecording: (transcribe = true) =>
    call<{ seconds: number; transcript: Transcript | null }>("POST", "/audio/stop", { transcribe }),
  cancelRecording: () => call<{ recording: boolean }>("POST", "/audio/cancel"),

  history: () => call<HistoryEntry[]>("GET", "/history"),
  clearHistory: () => call<{ deleted: number }>("DELETE", "/history"),
  closeBrowser: () => call<{ browser_open: boolean }>("POST", "/browser/close"),
};

export function errorMessage(err: unknown): string {
  if (err instanceof VicoApiError) return err.message;
  if (err instanceof Error) return err.message;
  return String(err);
}
