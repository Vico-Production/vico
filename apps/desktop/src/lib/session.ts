// The session driver: one summon, from Vico arriving to Vico leaving. It lives in the aura
// window (which stays visible for the whole session) and tells the prompt window what to
// show. The prompt sends back what the user did as intents.
import type { Reaction } from "../views/Looks";
import { actFor, type Act, type Metrics } from "./acting";
import { api, errorMessage } from "./api";
import { emit } from "./bus";
import { TERMINAL_STATES, type Language, type Run, type Step } from "./contracts";
import { promptFrame, type Look, type Mood, type Rect } from "./layout";
import { native, type Native } from "./native";

export type Phase =
  | "hidden"
  | "setup" // first run: pick a look, then one free access code
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
  | "staying" // the user asked Vico to stay: it dozes until called
  | "leaving";

export type Spots = Partial<Record<"peek" | "yoyo" | "possession_label", number>>;

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
  look: Look; // how Vico appears: chosen at setup, changed in settings
  target: Rect | null; // the window the user (or Vico) is working in, for Peek and Possession
  reaction: Reaction | null; // a short reaction to something that just happened
  reactionAt: number; // restarts the reaction's animation when it repeats
  act: Act | null; // the step being acted out, at its real place on screen
  followUp: boolean; // listening for a next request without taking the keyboard
  staying: boolean; // the user asked Vico to stay until told to go
  micHint: string | null; // what to do when the microphone gives no sound
  spots: Spots; // where the user dragged or told each look to go
}

export type Intent =
  | { type: "hello" }
  | { type: "summon" }
  | { type: "settings" }
  | { type: "escape" }
  | { type: "type"; text: string }
  | { type: "stop-listening" }
  | { type: "listen" }
  | { type: "type-instead" }
  | { type: "submit" }
  | { type: "approve"; confirm: boolean }
  | { type: "reject" }
  | { type: "configured"; look: Look }
  | { type: "reset" }
  | { type: "spot"; spots: Spots };

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
  look: "peek",
  target: null,
  reaction: null,
  reactionAt: 0,
  act: null,
  followUp: false,
  staying: false,
  micHint: null,
  spots: {},
};

/** What the look should be doing in each phase. */
export function moodFor(phase: Phase): Mood {
  switch (phase) {
    case "listening":
    case "review":
    case "typing":
    case "question":
      return "listen";
    case "transcribing":
    case "thinking":
    case "cooling":
      return "think";
    case "working":
      return "work";
    case "approval":
      return "ask";
    case "done":
    case "staying":
      return "done";
    case "error":
      return "sad";
    default:
      return "away"; // hidden, leaving, and setup (which has its own panel)
  }
}

const REVIEW_MS = 900; // a heard request goes on its own unless the user starts editing
// Natural speech has pauses: wait this long after the last word before treating it as the end,
// and longer while the request is still short (people pause after "Vico, can you...").
const SILENCE_MS = 1500;
const SILENCE_SHORT_MS = 2100;
const SHORT_SPEECH_MS = 1600;
const NO_SPEECH_MS = 8000; // nothing said at all: stop and say so, instead of waiting 15 s
const FOLLOW_UP_MS = 10_000; // after a task, listen this long for a next request, then leave
const SPEECH_LEVEL = 0.03; // the lowest level that counts as speech, even in a silent room
const NOISE_MARGIN = 2.5; // speech must be this many times louder than the room
const ROOM_MAX = 0.06; // louder than this is never just the room
const RESULT_MS = 3200; // how long a result stays up before the follow-up
const ERROR_MS = 7000;
const LEAVE_MS = 900;

const REACTION_MS: Partial<Record<Reaction, number>> = {
  arrive: 900, gotit: 900, celebrate: 2000, shrug: 2600, refuse: 2600, bye: 1500, stay: 2400, move: 1800,
  huh: 2200, greet: 1800,
};

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

/** Where "move to the left / top corner / out of my way" puts each look. */
function spotFor(look: Look, where: string, spots: Spots): Spots {
  if (look === "possession") {
    const bottom = where.startsWith("bottom") ? 1 : where.startsWith("top") ? 0 : 1 - (spots.possession_label ?? 0);
    return { ...spots, possession_label: bottom };
  }
  const key = look === "peek" ? "peek" : "yoyo";
  const now = spots[key] ?? (look === "peek" ? 0.5 : 0.92);
  const x = where.endsWith("left") ? 0.1 : where.endsWith("right") ? 0.9 : now > 0.5 ? 0.12 : 0.88;
  return { ...spots, [key]: x };
}

export class VicoDriver {
  state: Session = INITIAL;
  private listeners = new Set<(s: Session) => void>();
  private run: Run | null = null;
  private finished: string | null = null; // the run whose ending was already handled
  private poller: number | null = null;
  private levelPoller: number | null = null;
  private timer: number | null = null;
  private reactionTimer: number | null = null;
  private wakePoller: number | null = null;
  private heard = false;
  private quietSince = 0;
  private speechSince = 0;
  private misses = 0; // listens in a row that heard nothing
  private lastPhase: Phase = "hidden";
  private busy = false;
  private voice = false;
  private audio: HTMLAudioElement | null = null;
  private look: Look = "peek";
  private spots: Spots = {};
  private metrics: Metrics | null = null;
  private targetPoller: number | null = null;

  constructor(private readonly windows: Native = native) {}

  subscribe(fn: (s: Session) => void): () => void {
    this.listeners.add(fn);
    fn(this.state);
    return () => this.listeners.delete(fn);
  }

  private set(patch: Partial<Session>) {
    // The look and its spot survive every reset of the session; only the user changes them.
    this.state = { ...this.state, ...patch, look: this.look, spots: this.spots };
    this.listeners.forEach((fn) => fn(this.state));
    void emit(STATE_EVENT, this.state);
    if (this.state.phase !== this.lastPhase) {
      const before = this.lastPhase;
      this.lastPhase = this.state.phase;
      void this.syncWindows(before);
    }
  }

  private react(reaction: Reaction | null) {
    if (this.reactionTimer !== null) window.clearTimeout(this.reactionTimer);
    this.reactionTimer = null;
    this.set({ reaction, reactionAt: Date.now() });
    const ms = reaction ? REACTION_MS[reaction] : undefined;
    if (ms) this.reactionTimer = window.setTimeout(() => this.set({ reaction: null }), ms);
  }

  /** The prompt takes the keyboard only when Vico needs your words, never while it follows up. */
  private promptWanted(): boolean {
    return PROMPT_PHASES.includes(this.state.phase) && !(this.state.followUp && this.state.phase === "listening");
  }

  private async syncWindows(before: Phase) {
    const now = this.state.phase;
    if (now === "hidden") {
      this.followTarget(false);
      await this.windows.hidePrompt();
      await this.windows.hideAura();
      return;
    }
    if (before === "hidden") {
      this.followTarget(true);
      await this.windows.showAura();
    }
    if (this.promptWanted()) {
      await this.placePrompt();
      await this.windows.showPrompt();
    } else await this.windows.hidePrompt(); // hand the keyboard back to the user's apps
  }

  /** The prompt window sits next to the look (or inside the possessed window). */
  private async placePrompt() {
    if (!this.promptWanted()) return;
    const screen = { width: window.innerWidth, height: window.innerHeight };
    const frame = promptFrame(this.look, this.state.phase, moodFor(this.state.phase), screen, this.state.target, this.spots);
    await this.windows.placePrompt?.(frame);
  }

  /** Peek and Possession follow the window being worked in; Yo-yo stays in its corner. */
  private followTarget(on: boolean) {
    if (this.targetPoller !== null) window.clearInterval(this.targetPoller);
    this.targetPoller = null;
    if (!on || !this.windows.foregroundRect || this.look === "yoyo") return;
    const poll = async () => {
      const rect = (await this.windows.foregroundRect?.().catch(() => null)) ?? null;
      const before = this.state.target;
      const keys: (keyof Rect)[] = ["x", "y", "width", "height"];
      const same = before && rect && keys.every((k) => Math.abs(before[k] - rect[k]) < 2);
      if (same || (!before && !rect)) return;
      this.set({ target: rect });
      if (this.look === "possession" && !["setup", "settings"].includes(this.state.phase)) await this.placePrompt();
    };
    void poll();
    this.targetPoller = window.setInterval(() => void poll(), 250);
  }

  private remember(look: Look | undefined | null, spots?: Spots | null) {
    let changed = false;
    if (look && look !== this.look) {
      this.look = look;
      changed = true;
    }
    if (spots && JSON.stringify(spots) !== JSON.stringify(this.spots)) {
      this.spots = spots;
      changed = true;
    }
    if (changed) this.set({});
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
    // The engine can take a while on its very first start; keep asking for up to a minute.
    for (let attempt = 0; attempt < 60; attempt++) {
      try {
        const settings = await api.settings();
        this.remember(settings.look, settings.spots);
        this.metrics = (await this.windows.auraMetrics?.()) ?? null;
        const launch = await this.windows.launchInfo?.();
        if (launch) this.watchForWakePhrase(); // listening for "Vico" from the moment it is installed
        if (this.state.phase !== "hidden") return; // the user already summoned Vico
        if (!settings.onboarding_complete) return this.set({ ...INITIAL, phase: "setup" });
        if (launch && !launch.autostart) {
          // Opened by hand (or by the installer): show that Vico is running and how to call it.
          const call = launch.shortcut ? `press ${launch.shortcut}` : "click my tray icon";
          this.set({ ...INITIAL, phase: "done", narration: "",
            message: `I'm ready. Just say "Vico" or ${call} whenever you need me.`, localized: null });
          this.react("greet");
          this.timer = window.setTimeout(() => this.leave(), 3600);
        }
        return;
      } catch {
        await new Promise((r) => window.setTimeout(r, 1000));
      }
    }
  }

  /** "Vico" is heard by the engine; while Vico is away or idle, ask it often whether it was. */
  private watchForWakePhrase() {
    if (this.wakePoller !== null) return;
    this.wakePoller = window.setInterval(async () => {
      if (!["hidden", "staying", "done", "error"].includes(this.state.phase) || this.busy) return;
      try {
        if ((await api.wake()).woke) void this.summon(true);
      } catch {
        /* the engine is restarting; ask again shortly */
      }
    }, 200);
  }

  dispatch(intent: Intent) {
    switch (intent.type) {
      case "hello":
        return this.set({});
      case "summon":
        return void this.summon();
      case "settings":
        this.clearTimer();
        return this.set({ phase: "settings", followUp: false });
      case "escape":
        return void this.escape();
      case "type":
        return void this.type(intent.text);
      case "type-instead":
        return void this.type("");
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
      case "reset":
        this.clearTimer();
        this.spots = {};
        return this.set({ ...INITIAL, phase: "setup" });
      case "spot":
        this.spots = intent.spots;
        this.set({});
        void api.updateSettings({ spots: intent.spots }).catch(() => undefined);
        return;
      case "configured":
        this.remember(intent.look);
        this.set({ phase: "done", narration: "", localized: null,
          message: "You're all set. Just say \"Vico\" or press Win + Alt + V whenever you need me." });
        this.react("celebrate");
        this.timer = window.setTimeout(() => this.leave(), 3600);
        return;
    }
  }

  /** `woke`: summoned by its name, and the engine is already recording what follows. */
  async summon(woke = false) {
    const active = this.run && !TERMINAL_STATES.includes(this.run.state);
    const busyPhases = ["typing", "review", "setup", "settings", "transcribing"];
    if (active || busyPhases.includes(this.state.phase) || (this.state.phase === "listening" && !this.state.followUp)) {
      // Already here: summoning again while listening means "I'm done talking".
      if (woke) void api.cancelRecording().catch(() => undefined);
      if (this.state.phase === "listening") await this.stopListening();
      else this.set({});
      return;
    }
    const arriving = this.state.phase === "hidden" || this.state.phase === "leaving";
    this.clearTimer();
    this.stopPolling();
    if (this.state.phase === "listening") void api.cancelRecording().catch(() => undefined); // a follow-up
    this.run = null;
    this.misses = 0;
    let speech = false;
    let offline = false;
    try {
      const [settings, health] = await Promise.all([api.settings(), api.health()]);
      this.remember(settings.look, settings.spots);
      if (!settings.onboarding_complete || (!health.cloud_ready && health.online)) {
        if (woke) void api.cancelRecording().catch(() => undefined);
        this.set({ ...INITIAL, phase: "setup" });
        return;
      }
      speech = health.speech_ready;
      this.voice = Boolean(health.voice_ready);
      offline = !health.online;
    } catch (err) {
      if (woke) void api.cancelRecording().catch(() => undefined);
      this.set({ ...INITIAL, phase: "error", message: errorMessage(err) });
      this.timer = window.setTimeout(() => this.leave(), ERROR_MS);
      return;
    }
    if (woke && !speech) void api.cancelRecording().catch(() => undefined);
    // Voice first: Vico comes up listening; typing is one click (or keystroke) away.
    this.set({ ...INITIAL, phase: speech ? "listening" : "typing", speech, offline, staying: this.state.staying,
      target: this.state.target, narration: offline ? "Offline · simple typed commands only" : "" });
    if (arriving) this.react("arrive");
    if (speech) await this.listen(woke);
  }

  async listen(alreadyRecording = false, followUp = false) {
    this.heard = false;
    this.quietSince = Date.now();
    this.speechSince = 0;
    const started = Date.now();
    let floor = 0; // the room's background level, learned while the user is quiet
    if (this.levelPoller !== null) window.clearInterval(this.levelPoller);
    this.levelPoller = null;
    this.set({ phase: "listening", text: "", level: 0, followUp, micHint: null, act: null,
      narration: followUp ? "Anything else? I'm listening" : "" });
    try {
      if (!alreadyRecording) await api.startRecording();
    } catch (err) {
      if (followUp) return this.leave();
      this.set({ phase: "typing", followUp: false, narration: errorMessage(err) });
      return;
    }
    const limit = followUp ? FOLLOW_UP_MS : NO_SPEECH_MS;
    this.levelPoller = window.setInterval(async () => {
      if (this.state.phase !== "listening") return;
      try {
        const status = await api.recordingStatus();
        const now = Date.now();
        // A silent microphone is a hint, never a reason to stop: some microphones send pure
        // silence until someone speaks, and Vico tries the others by itself.
        const hint = status.silent ? "I can't hear your microphone yet. Speak up, or check it isn't muted." : null;
        if (hint !== this.state.micHint) this.set({ micHint: hint });
        // Only quiet readings teach the room level, so someone who talks straight away is still heard.
        if (!this.heard && status.level < ROOM_MAX) {
          floor = floor === 0 ? status.level : Math.min(floor * 1.02 + 0.001, status.level);
        }
        if (status.level > Math.max(SPEECH_LEVEL, floor * NOISE_MARGIN)) {
          if (!this.heard) this.speechSince = now;
          this.heard = true;
          this.quietSince = now;
        }
        this.set({ level: status.level });
        const spoken = now - this.speechSince;
        const pause = spoken < SHORT_SPEECH_MS ? SILENCE_SHORT_MS : SILENCE_MS;
        const finished = this.heard && now - this.quietSince > pause;
        if (finished || status.full || now - started > status.max_s * 1000) {
          void this.stopListening();
        } else if (!this.heard && now - started > limit) {
          void this.nothingHeard(followUp);
        }
      } catch {
        /* a missed level reading is harmless */
      }
    }, 110);
  }

  /** Nobody spoke: never send silence anywhere. */
  private async nothingHeard(followUp: boolean) {
    if (this.levelPoller !== null) window.clearInterval(this.levelPoller);
    this.levelPoller = null;
    await api.cancelRecording().catch(() => undefined);
    if (followUp) {
      if (this.state.staying) return this.set({ phase: "staying", followUp: false, level: 0, narration: "" });
      this.react("bye");
      this.timer = window.setTimeout(() => this.leave(), 900);
      return;
    }
    this.misses += 1;
    this.react("huh");
    if (this.misses >= 2) {
      this.set({ phase: "typing", level: 0, narration: this.state.micHint ??
        "I didn't hear anything. Type it, or call me again." });
      return;
    }
    this.set({ narration: "I didn't hear anything. Say it again?" });
    await this.listen();
  }

  async stopListening() {
    if (this.state.phase !== "listening" || this.busy) return;
    this.busy = true;
    if (this.levelPoller !== null) window.clearInterval(this.levelPoller);
    this.levelPoller = null;
    this.set({ phase: "transcribing", level: 0, followUp: false });
    try {
      const result = await api.stopRecording(true);
      const text = result.transcript?.text.trim() ?? "";
      if (!text) {
        this.react("huh");
        this.set({ phase: "typing", narration: "I didn't catch that. Say it again, or type it." });
        return;
      }
      this.react("gotit");
      this.set({ phase: "review", text, reviewUntil: Date.now() + REVIEW_MS });
      this.timer = window.setTimeout(() => void this.submit(), REVIEW_MS);
    } catch (err) {
      this.react("huh");
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
    this.set({ phase, text, reviewUntil: null, level: 0, followUp: false });
  }

  async submit() {
    this.clearTimer();
    const text = this.state.text.trim();
    if (!text || this.busy) return;
    if (/^(vico (settings|setup|reset)|change (my )?(key|code)s?)$/i.test(text)) {
      return this.set({ ...INITIAL, phase: "settings", speech: this.state.speech });
    }
    this.busy = true;
    try {
      if (this.state.phase === "question" && this.run) {
        this.set({ phase: "thinking", narration: "Got it", question: null, reviewUntil: null });
        this.run = await api.reply(this.run.id, text);
      } else {
        this.set({ phase: "thinking", narration: "Understanding you", reviewUntil: null, act: null });
        this.run = await api.startRun(text);
      }
      this.startPolling();
    } catch (err) {
      this.fail(errorMessage(err), false);
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
        this.fail(errorMessage(err), false);
      }
    }, 200);
  }

  /** The step being acted out: the newest one that has started, at its real place on screen. */
  private actOf(run: Run): Act | null {
    if (!["executing", "verifying", "planning", "validating"].includes(run.state)) return null;
    const step = [...run.steps].reverse().find((s) => ["running", "succeeded", "unverified", "failed"].includes(s.status));
    return step ? actFor(step, this.metrics) : null;
  }

  private apply(run: Run) {
    // A status check still in flight when a run ends must not handle its ending twice.
    if (run.id === this.finished) return;
    if (TERMINAL_STATES.includes(run.state)) this.finished = run.id;
    this.run = run;
    const pending = run.pending_step_id ? run.steps.find((s) => s.id === run.pending_step_id) ?? null : null;
    const act = this.actOf(run);
    const same = (a: Act | null, b: Act | null) => JSON.stringify(a) === JSON.stringify(b);
    switch (run.state) {
      case "awaiting_approval":
        if (this.state.phase !== "approval" || this.state.step?.id !== pending?.id) {
          this.set({ phase: "approval", step: pending, narration: "", act: null });
        }
        return;
      case "awaiting_clarification":
        if (this.state.phase !== "question") this.set({ phase: "question", question: run.question, text: "", act: null });
        return;
      case "cooling_down":
        this.set({ phase: "cooling", cooldownUntil: run.cooldown_until ? Date.parse(run.cooldown_until) : null,
          narration: "Your free AI key is resting · Vico will carry on by itself", act: null });
        return;
      case "completed":
        this.stopPolling();
        if (run.control) return this.obey(run);
        this.set({ phase: "done", message: run.message, localized: run.message_localized, narration: "", step: null,
          act: null });
        this.react("celebrate");
        this.afterResult();
        void this.speakResult(run.message_localized || run.message, run.language);
        return;
      case "failed":
        return this.fail(run.message || run.error?.message || "Something went wrong.", run.error?.code === "policy_denied");
      case "cancelled":
        this.stopPolling();
        this.set({ phase: "done", message: run.message || "Stopped. Nothing else was done.", localized: null, act: null });
        this.timer = window.setTimeout(() => this.leave(), 2600);
        return;
      default: {
        const phase = run.state === "executing" || run.state === "verifying" ? "working" : "thinking";
        const narration = narrationFor(run);
        if (this.state.phase !== phase || this.state.narration !== narration || !same(this.state.act, act)) {
          this.set({ phase, narration, step: null, cooldownUntil: null, act });
        }
      }
    }
  }

  /** The request was about Vico itself: stay, go, move somewhere, or a greeting. */
  private obey(run: Run) {
    const control = run.control!;
    const message = run.message_localized || run.message;
    if (control.action === "go") {
      this.set({ phase: "done", message, localized: null, staying: false, act: null });
      this.react("bye");
      this.timer = window.setTimeout(() => this.leave(), 1500);
      return;
    }
    if (control.action === "stay") {
      this.set({ phase: "done", message, localized: null, staying: true, act: null });
      this.react("stay");
      this.timer = window.setTimeout(() => this.set({ phase: "staying", message: null, narration: "" }), 2400);
      return;
    }
    if (control.action === "move") {
      this.spots = spotFor(this.look, control.where ?? "away", this.spots);
      void api.updateSettings({ spots: this.spots }).catch(() => undefined);
      this.set({ phase: "done", message, localized: null, act: null });
      this.react("move");
      this.afterResult();
      return;
    }
    // A greeting: answer in the user's language, then keep listening for what they want.
    this.set({ phase: "done", message, localized: null, act: null });
    this.react("greet");
    this.timer = window.setTimeout(() => void this.listen(false, true), 1700);
  }

  /** After a result: stay a little and listen for a next request (without taking the keyboard). */
  private afterResult() {
    this.clearTimer();
    this.timer = window.setTimeout(() => {
      if (this.state.phase !== "done") return;
      if (this.state.staying) return this.set({ phase: "staying", message: null, narration: "" });
      if (this.state.speech) void this.listen(false, true);
      else this.timer = window.setTimeout(() => this.leave(), FOLLOW_UP_MS);
    }, RESULT_MS);
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
      audio.onended = audio.onerror = () => {
        URL.revokeObjectURL(url);
        this.audio = null;
      };
      await audio.play();
    } catch {
      /* the answer stays on screen as text */
    }
  }

  private fail(message: string, refused: boolean) {
    this.stopPolling();
    this.set({ phase: "error", message, narration: "", step: null, act: null });
    this.react(refused ? "refuse" : "shrug");
    this.clearTimer();
    this.timer = window.setTimeout(() => (this.state.staying ? this.set({ phase: "staying", message: null })
      : this.leave()), ERROR_MS);
  }

  async decide(approved: boolean, confirm: boolean) {
    const step = this.state.step;
    if (!this.run || !step || this.state.phase !== "approval") return;
    this.set({ phase: approved ? "working" : "thinking", narration: approved ? step.effect : "Stopping", step: null });
    try {
      this.run = await api.decide(this.run.id, step.id, approved, confirm);
    } catch (err) {
      this.fail(errorMessage(err), false);
    }
  }

  async escape() {
    this.clearTimer();
    if (this.state.phase === "listening") void api.cancelRecording().catch(() => undefined);
    if (this.run && !TERMINAL_STATES.includes(this.run.state)) {
      void api.cancel(this.run.id).catch(() => undefined);
    }
    this.set({ staying: false });
    this.leave();
  }

  /** Stop every timer and poller (the window hosting the driver is going away). */
  dispose() {
    this.clearTimer();
    this.stopPolling();
    this.followTarget(false);
    if (this.reactionTimer !== null) window.clearTimeout(this.reactionTimer);
    if (this.wakePoller !== null) window.clearInterval(this.wakePoller);
    this.reactionTimer = this.wakePoller = null;
    this.listeners.clear();
  }

  leave() {
    this.clearTimer();
    this.audio?.pause();
    this.audio = null;
    this.stopPolling();
    if (this.state.phase === "hidden" || this.state.phase === "leaving") return;
    if (this.state.phase === "listening") void api.cancelRecording().catch(() => undefined);
    this.set({ phase: "leaving", level: 0, act: null, followUp: false });
    this.timer = window.setTimeout(() => {
      this.run = null;
      this.set({ ...INITIAL });
    }, LEAVE_MS);
  }
}
