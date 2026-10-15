// The session driver: one summon, from the first glow to the last drop evaporating.
// It lives in the aura window (which stays visible for the whole session) and tells the
// prompt window what to show. The prompt sends back what the user did as intents.
import { api, errorMessage } from "./api";
import { emit } from "./bus";
import { TERMINAL_STATES, type Language, type Run, type Step } from "./contracts";
import { native, type Native } from "./native";

export type Phase =
  | "hidden"
  | "setup" // first run: one free access code
  | "settings"
  | "listening"
  | "transcribing"
  | "review" // what Vico heard, about to go
  | "typing"
  | "thinking"
  | "approval"
  | "question"
  | "working"
  | "cooling"
  | "done"
  | "error"
  | "leaving";

export interface Session {
  phase: Phase;
  level: number; // microphone level, 0..1
  text: string; // what the user said or typed
  narration: string; // what Vico is doing right now
  step: Step | null; // the step waiting for approval
  question: string | null;
  cooldownUntil: number | null; // epoch ms
  message: string | null;
  localized: string | null;
  reviewUntil: number | null; // epoch ms when a heard request goes automatically
  speech: boolean; // the microphone path is ready
  offline: boolean;
}

export type Intent =
  | { type: "hello" }
  | { type: "summon" }
  | { type: "settings" }
  | { type: "escape" }
  | { type: "type"; text: string }
  | { type: "stop-listening" }
  | { type: "listen" }
  | { type: "submit" }
  | { type: "approve"; confirm: boolean }
  | { type: "reject" }
  | { type: "configured" };

export const STATE_EVENT = "vico://state";
export const INTENT_EVENT = "vico://intent";

/** Phases in which the prompt window is shown and takes the keyboard. */
export const PROMPT_PHASES: Phase[] = [
  "setup",
  "settings",
  "listening",
  "transcribing",
  "review",
  "typing",
  "question",
  "approval",
];

export const INITIAL: Session = {
  phase: "hidden",
  level: 0,
  text: "",
  narration: "",
  step: null,
  question: null,
  cooldownUntil: null,
  message: null,
  localized: null,
  reviewUntil: null,
  speech: false,
  offline: false,
};

const REVIEW_MS = 1800; // a heard request goes on its own unless the user starts editing
const SILENCE_MS = 1100; // stop listening after this much quiet following speech
const SPEECH_LEVEL = 0.07;
const DONE_MS = 5200;
const ERROR_MS = 7000;
const LEAVE_MS = 900;

function narrationFor(run: Run): string {
  const last = run.steps[run.steps.length - 1];
  switch (run.state) {
    case "normalizing":
      return "Understanding you";
    case "planning":
      return run.steps.length ? "Deciding what to do next" : "Thinking";
    case "validating":
      return "Making sure it's safe";
    case "executing":
      return last?.effect || "Working";
    case "verifying":
      return "Checking it worked";
    default:
      return "";
  }
}

export class VicoDriver {
  state: Session = INITIAL;
  private listeners = new Set<(s: Session) => void>();
  private run: Run | null = null;
  private poller: number | null = null;
  private levelPoller: number | null = null;
  private timer: number | null = null;
  private heard = false;
  private quietSince = 0;
  private lastPhase: Phase = "hidden";
  private busy = false;
  private voice = false;
  private audio: HTMLAudioElement | null = null;

  constructor(private readonly windows: Native = native) {}

  subscribe(fn: (s: Session) => void): () => void {
    this.listeners.add(fn);
    fn(this.state);
    return () => this.listeners.delete(fn);
  }

  private set(patch: Partial<Session>) {
    this.state = { ...this.state, ...patch };
    this.listeners.forEach((fn) => fn(this.state));
    void emit(STATE_EVENT, this.state);
    if (this.state.phase !== this.lastPhase) {
      const before = this.lastPhase;
      this.lastPhase = this.state.phase;
      void this.syncWindows(before);
    }
  }

  private async syncWindows(before: Phase) {
    const now = this.state.phase;
    if (now === "hidden") {
      await this.windows.hidePrompt();
      await this.windows.hideAura();
      return;
    }
    if (before === "hidden") await this.windows.showAura();
    if (PROMPT_PHASES.includes(now)) await this.windows.showPrompt();
    else await this.windows.hidePrompt(); // hand the keyboard back to the user's apps
  }

  private clearTimer() {
    if (this.timer !== null) window.clearTimeout(this.timer);
    this.timer = null;
  }

  private stopPolling() {
    if (this.poller !== null) window.clearInterval(this.poller);
    if (this.levelPoller !== null) window.clearInterval(this.levelPoller);
    this.poller = this.levelPoller = null;
  }

  // --- entry points ---------------------------------------------------------------------
  async boot() {
    try {
      const settings = await api.settings();
      if (!settings.onboarding_complete) this.set({ ...INITIAL, phase: "setup" });
    } catch {
      /* the engine may still be starting; the next summon checks again */
    }
  }

  dispatch(intent: Intent) {
    switch (intent.type) {
      case "hello":
        return this.set({});
      case "summon":
        return void this.summon();
      case "settings":
        this.clearTimer();
        return this.set({ phase: "settings" });
      case "escape":
        return void this.escape();
      case "type":
        return void this.type(intent.text);
      case "stop-listening":
        return void this.stopListening();
      case "listen":
        return void this.listen();
      case "submit":
        return void this.submit();
      case "approve":
        return void this.decide(true, intent.confirm);
      case "reject":
        return void this.decide(false, false);
      case "configured":
        this.set({ phase: "done", narration: "", message: "You're all set. Press Win + Alt + V whenever you need me.", localized: null });
        this.timer = window.setTimeout(() => this.leave(), 3600);
        return;
    }
  }

  async summon() {
    const active = this.run && !TERMINAL_STATES.includes(this.run.state);
    if (active || ["listening", "typing", "review", "setup", "settings"].includes(this.state.phase)) {
      // Already here: summoning again while listening means "I'm done talking".
      if (this.state.phase === "listening") await this.stopListening();
      else this.set({});
      return;
    }
    this.clearTimer();
    this.stopPolling();
    this.run = null;
    let speech = false;
    let offline = false;
    try {
      const [settings, health] = await Promise.all([api.settings(), api.health()]);
      if (!settings.onboarding_complete || (!health.cloud_ready && health.online)) {
        this.set({ ...INITIAL, phase: "setup" });
        return;
      }
      speech = health.speech_ready;
      this.voice = Boolean(health.voice_ready);
      offline = !health.online;
    } catch (err) {
      this.set({ ...INITIAL, phase: "error", message: errorMessage(err) });
      this.timer = window.setTimeout(() => this.leave(), ERROR_MS);
      return;
    }
    this.set({ ...INITIAL, phase: speech ? "listening" : "typing", speech, offline,
      narration: offline ? "Offline · simple typed commands only" : "" });
    if (speech) await this.listen();
  }

  async listen() {
    this.heard = false;
    this.quietSince = Date.now();
    const started = Date.now();
    this.set({ phase: "listening", text: "", level: 0 });
    try {
      await api.startRecording();
    } catch (err) {
      this.set({ phase: "typing", narration: errorMessage(err) });
      return;
    }
    this.levelPoller = window.setInterval(async () => {
      if (this.state.phase !== "listening") return;
      try {
        const status = await api.recordingStatus();
        const now = Date.now();
        if (status.level > SPEECH_LEVEL) {
          this.heard = true;
          this.quietSince = now;
        }
        this.set({ level: status.level });
        const quiet = this.heard && now - this.quietSince > SILENCE_MS;
        if (quiet || status.full || now - started > status.max_s * 1000) void this.stopListening();
      } catch {
        /* a missed level reading is harmless */
      }
    }, 110);
  }

  async stopListening() {
    if (this.state.phase !== "listening" || this.busy) return;
    this.busy = true;
    if (this.levelPoller !== null) window.clearInterval(this.levelPoller);
    this.levelPoller = null;
    this.set({ phase: "transcribing", level: 0 });
    try {
      const result = await api.stopRecording(true);
      const text = result.transcript?.text.trim() ?? "";
      if (!text) {
        this.set({ phase: "typing", narration: "I didn't catch that. Type it, or press Win + Alt + V to talk again." });
        return;
      }
      this.set({ phase: "review", text, reviewUntil: Date.now() + REVIEW_MS });
      this.timer = window.setTimeout(() => void this.submit(), REVIEW_MS);
    } catch (err) {
      this.set({ phase: "typing", narration: errorMessage(err) });
    } finally {
      this.busy = false;
    }
  }

  async type(text: string) {
    if (this.state.phase === "listening") {
      if (this.levelPoller !== null) window.clearInterval(this.levelPoller);
      this.levelPoller = null;
      void api.cancelRecording().catch(() => undefined);
    }
    this.clearTimer();
    const phase = this.state.phase === "question" ? "question" : "typing";
    this.set({ phase, text, reviewUntil: null, level: 0 });
  }

  async submit() {
    this.clearTimer();
    const text = this.state.text.trim();
    if (!text || this.busy) return;
    this.busy = true;
    try {
      if (this.state.phase === "question" && this.run) {
        this.set({ phase: "thinking", narration: "Got it", question: null, reviewUntil: null });
        this.run = await api.reply(this.run.id, text);
      } else {
        this.set({ phase: "thinking", narration: "Understanding you", reviewUntil: null });
        this.run = await api.startRun(text);
      }
      this.startPolling();
    } catch (err) {
      this.fail(errorMessage(err));
    } finally {
      this.busy = false;
    }
  }

  private startPolling() {
    if (this.poller !== null) window.clearInterval(this.poller);
    this.poller = window.setInterval(async () => {
      if (!this.run) return;
      try {
        this.apply(await api.getRun(this.run.id));
      } catch (err) {
        this.fail(errorMessage(err));
      }
    }, 280);
  }

  private apply(run: Run) {
    this.run = run;
    const pending = run.pending_step_id ? run.steps.find((s) => s.id === run.pending_step_id) ?? null : null;
    switch (run.state) {
      case "awaiting_approval":
        if (this.state.phase !== "approval" || this.state.step?.id !== pending?.id) {
          this.set({ phase: "approval", step: pending, narration: "" });
        }
        return;
      case "awaiting_clarification":
        if (this.state.phase !== "question") this.set({ phase: "question", question: run.question, text: "" });
        return;
      case "cooling_down":
        this.set({ phase: "cooling", cooldownUntil: run.cooldown_until ? Date.parse(run.cooldown_until) : null,
          narration: "Your free AI key is resting · Vico will carry on by itself" });
        return;
      case "completed":
        this.stopPolling();
        this.set({ phase: "done", message: run.message, localized: run.message_localized, narration: "", step: null });
        this.timer = window.setTimeout(() => this.leave(), DONE_MS);
        void this.speakResult(run.message_localized || run.message, run.language);
        return;
      case "failed":
        return this.fail(run.message || run.error?.message || "Something went wrong.");
      case "cancelled":
        this.stopPolling();
        this.set({ phase: "done", message: run.message || "Stopped. Nothing else was done.", localized: null });
        this.timer = window.setTimeout(() => this.leave(), 2600);
        return;
      default: {
        const phase = run.state === "executing" || run.state === "verifying" ? "working" : "thinking";
        const narration = narrationFor(run);
        if (this.state.phase !== phase || this.state.narration !== narration) {
          this.set({ phase, narration, step: null, cooldownUntil: null });
        }
      }
    }
  }

  /** Speak the answer in the user's language (YarnGPT on their speech server), from memory. */
  private async speakResult(text: string | null, language: string) {
    if (!this.voice || !text || !["en", "yo", "ha", "ig"].includes(language)) return;
    try {
      const out = await api.speak(text, language as Language);
      if (this.state.phase !== "done") return;
      const bytes = Uint8Array.from(atob(out.audio_b64), (c) => c.charCodeAt(0));
      const url = URL.createObjectURL(new Blob([bytes], { type: out.mime }));
      const audio = new Audio(url);
      this.audio = audio;
      this.clearTimer(); // stay until the voice has finished
      audio.onended = audio.onerror = () => {
        URL.revokeObjectURL(url);
        this.audio = null;
        this.timer = window.setTimeout(() => this.leave(), 1600);
      };
      await audio.play();
    } catch {
      /* the answer stays on screen as text */
    }
  }

  private fail(message: string) {
    this.stopPolling();
    this.set({ phase: "error", message, narration: "", step: null });
    this.clearTimer();
    this.timer = window.setTimeout(() => this.leave(), ERROR_MS);
  }

  async decide(approved: boolean, confirm: boolean) {
    const step = this.state.step;
    if (!this.run || !step || this.state.phase !== "approval") return;
    this.set({ phase: approved ? "working" : "thinking", narration: approved ? step.effect : "Stopping", step: null });
    try {
      this.run = await api.decide(this.run.id, step.id, approved, confirm);
    } catch (err) {
      this.fail(errorMessage(err));
    }
  }

  async escape() {
    this.clearTimer();
    if (this.state.phase === "listening") void api.cancelRecording().catch(() => undefined);
    if (this.run && !TERMINAL_STATES.includes(this.run.state)) {
      void api.cancel(this.run.id).catch(() => undefined);
    }
    this.leave();
  }

  leave() {
    this.clearTimer();
    this.audio?.pause();
    this.audio = null;
    this.stopPolling();
    if (this.state.phase === "hidden" || this.state.phase === "leaving") return;
    this.set({ phase: "leaving", level: 0 });
    this.timer = window.setTimeout(() => {
      this.run = null;
      this.set({ ...INITIAL });
    }, LEAVE_MS);
  }
}
