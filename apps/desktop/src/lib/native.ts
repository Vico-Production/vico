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

export interface Native {
  showAura(): Promise<void>;
  hideAura(): Promise<void>;
  showPrompt(): Promise<void>;
  hidePrompt(): Promise<void>;
  launchInfo?(): Promise<LaunchInfo | null>;
  placePrompt?(frame: Rect): Promise<void>;
  foregroundRect?(): Promise<Rect | null>;
}

export const native: Native = {
  showAura: () => call("aura_show"),
  hideAura: () => call("aura_hide"),
  showPrompt: () => call("prompt_show"),
  hidePrompt: () => call("prompt_hide"),
  launchInfo,
  placePrompt,
  foregroundRect,
};
