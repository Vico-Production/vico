// Mirrors services/agent/app/contracts.py. Keep the two in sync (checked by contract fixtures).

export const API_VERSION = "1";

export type Language = "en" | "yo" | "ha" | "ig" | "pcm";
export const LANGUAGES: Language[] = ["en", "yo", "ha", "ig", "pcm"];
export const LANGUAGE_NAMES: Record<Language, string> = {
  en: "English",
  yo: "Yoruba",
  ha: "Hausa",
  ig: "Igbo",
  pcm: "Nigerian Pidgin",
};
// BCP-47 tags used to find a system voice for speech output.
export const SPEECH_TAGS: Record<Language, string[]> = {
  en: ["en-NG", "en-GB", "en-US", "en"],
  yo: ["yo-NG", "yo"],
  ha: ["ha-NG", "ha"],
  ig: ["ig-NG", "ig"],
  pcm: ["pcm-NG", "pcm"],
};

export type RunState =
  | "idle"
  | "normalizing"
  | "planning"
  | "validating"
  | "awaiting_approval"
  | "awaiting_clarification"
  | "cooling_down"
  | "executing"
  | "verifying"
  | "completed"
  | "failed"
  | "cancelled";

export const TERMINAL_STATES: RunState[] = ["completed", "failed", "cancelled"];

export type ProviderStatus = "ready" | "not_configured" | "offline" | "rate_limited" | "error" | "disabled";

export type ErrorCode =
  | "unauthorized"
  | "validation_error"
  | "not_found"
  | "policy_denied"
  | "consent_required"
  | "provider_unavailable"
  | "provider_auth"
  | "rate_limited"
  | "timeout"
  | "offline"
  | "invalid_plan"
  | "cancelled"
  | "mic_unavailable"
  | "unsupported"
  | "conflict"
  | "internal"
  // UI-only: the local sidecar could not be reached.
  | "sidecar_unavailable";

export interface ApiError {
  code: ErrorCode;
  message: string;
  retryable: boolean;
  retry_after_s: number | null;
}

export interface Envelope<T> {
  api_version: string;
  ok: boolean;
  data: T | null;
  error: ApiError | null;
}

export type ProviderName = "groq" | "gemini" | "none";

export interface Settings {
  onboarding_complete: boolean;
  cloud_consent: boolean;
  require_approval: boolean;
  allow_send_without_approval: boolean;
  workspace: string;
  allowed_roots: string[];
  stt_provider: ProviderName;
  llm_provider: ProviderName;
  fallback_consent: boolean;
  stt_model: string | null;
  llm_model: string | null;
  daily_request_budget: number;
  max_steps: number;
  browser_channel: "auto" | "msedge" | "chrome" | "chromium";
  speech_server_url: string | null;
  voice_replies: boolean;
  wake_word: boolean;
  look: "peek" | "possession" | "yoyo";
  spots: Partial<Record<"peek" | "yoyo" | "possession_label", number>>;
}

export interface ProviderHealth {
  status: ProviderStatus;
  configured: boolean;
  requests_today: number;
  daily_budget: number;
  audio_seconds_today: number;
  rate_limited: boolean;
  cooldown_s: number;
}

export interface Health {
  version: string;
  platform: string;
  adapter: string;
  online: boolean;
  cloud_ready: boolean;
  speech_ready: boolean;
  voice_ready: boolean;
  cloud_consent: boolean;
  providers: Record<"groq" | "gemini" | "speech_server", ProviderHealth>;
  recording: boolean;
  browser_open: boolean;
}

export type StepStatus =
  | "proposed"
  | "awaiting_approval"
  | "running"
  | "succeeded"
  | "unverified"
  | "failed"
  | "denied"
  | "rejected";

export interface Step {
  id: string;
  tool: string;
  arguments: Record<string, unknown>;
  explanation: string;
  effect: string;
  targets: string[];
  outcome: "" | "allowed" | "approval_required" | "confirm_required" | "denied";
  reason: string;
  content_upload: boolean;
  approval: "pending" | "auto" | "approved" | "rejected" | "timed_out" | "denied";
  status: StepStatus;
  message: string;
  verification: string;
  verified: boolean;
  data: Record<string, unknown>;
  stage: { rect: { x: number; y: number; width: number; height: number }; kind: string } | null;
}

export interface Run {
  id: string;
  state: RunState;
  mode: "cloud" | "offline";
  language: Language | "auto";
  text: string;
  original: string;
  canonical: string;
  steps: Step[];
  pending_step_id: string | null;
  question: string | null;
  message: string | null;
  message_localized: string | null;
  error: { code: ErrorCode; message: string } | null;
  cooldown_until: string | null;
  control: { action: "stay" | "go" | "move" | "greet"; where?: string } | null;
  timeline: { state: string; at: string; note: string }[];
}

export interface Transcript {
  text: string;
  language: Language;
  provider: string;
  model: string;
  latency_ms: number;
  confidence: number | null;
}

export interface AudioStatus {
  recording: boolean;
  elapsed_s: number;
  max_s: number;
  level: number;
  full: boolean;
  silent?: boolean; // every microphone tried gives only digital silence
  device?: string;
}

export interface LanguageCapability {
  code: Language;
  name: string;
  text_label: "tested" | "untested";
  text_accuracy: number | null;
  speech_label: "untested" | "beta" | "unreliable";
  speech_accuracy: number | null;
  samples: { text: number; speech: number };
  note: string;
  experimental: boolean;
}

export interface HistoryEntry {
  id: number;
  created_at: string;
  language: string;
  summary: string;
  tool: string | null;
  approval: string;
  outcome: string;
  verified: boolean;
  detail: string | null;
}
