// Show and hide Vico's windows. No-ops in the browser preview.
import { inTauri } from "./bus";
import type { Rect } from "./layout";

async function call(command: string): Promise<void> {
  if (!inTauri) return;
  const { invoke } = await import("@tauri-apps/api/core");
  await invoke(command).catch(() => undefined);
}

export interface LaunchInfo {
  autostart: boolean; // started at sign-in, so stay quiet
  shortcut: string; // the shortcut that was actually registered
}

async function launchInfo(): Promise<LaunchInfo | null> {
  if (!inTauri) return null;
  const { invoke } = await import("@tauri-apps/api/core");
  return invoke<LaunchInfo>("launch_info").catch(() => null);
}

async function placePrompt(frame: Rect): Promise<void> {
  if (!inTauri) return;
  const { invoke } = await import("@tauri-apps/api/core");
  await invoke("prompt_frame", { ...frame }).catch(() => undefined);
}

/** The window the user is working in (never Vico's own), in aura coordinates; null if unknown. */
async function foregroundRect(): Promise<Rect | null> {
  if (!inTauri) return null;
  const { invoke } = await import("@tauri-apps/api/core");
  return invoke<Rect | null>("foreground_rect").catch(() => null);
}

/** Work-area origin and scale, to turn the engine's screen pixels into the aura's own. */
async function auraMetrics(): Promise<{ x: number; y: number; scale: number } | null> {
  if (!inTauri) return null;
  const { invoke } = await import("@tauri-apps/api/core");
  return invoke<{ x: number; y: number; scale: number } | null>("aura_metrics").catch(() => null);
}

/** Let the aura catch the mouse (only while it is over Vico's handle) or let clicks through. */
async function auraInteractive(on: boolean): Promise<void> {
  if (!inTauri) return;
  const { invoke } = await import("@tauri-apps/api/core");
  await invoke("aura_interactive", { on }).catch(() => undefined);
}

export interface Native {
  showAura(): Promise<void>;
  hideAura(): Promise<void>;
  showPrompt(): Promise<void>;
  hidePrompt(): Promise<void>;
  launchInfo?(): Promise<LaunchInfo | null>;
  placePrompt?(frame: Rect): Promise<void>;
  foregroundRect?(): Promise<Rect | null>;
  auraMetrics?(): Promise<{ x: number; y: number; scale: number } | null>;
  auraInteractive?(on: boolean): Promise<void>;
}

export const native: Native = {
  showAura: () => call("aura_show"),
  hideAura: () => call("aura_hide"),
  showPrompt: () => call("prompt_show"),
  hidePrompt: () => call("prompt_hide"),
  launchInfo,
  placePrompt,
  foregroundRect,
  auraMetrics,
  auraInteractive,
};
