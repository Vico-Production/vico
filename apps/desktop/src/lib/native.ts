// Show and hide Vico's windows. No-ops in the browser preview.
import { inTauri } from "./bus";

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

export interface Native {
  showAura(): Promise<void>;
  hideAura(): Promise<void>;
  showPrompt(): Promise<void>;
  hidePrompt(): Promise<void>;
  launchInfo?(): Promise<LaunchInfo | null>;
}

export const native: Native = {
  showAura: () => call("aura_show"),
  hideAura: () => call("aura_hide"),
  showPrompt: () => call("prompt_show"),
  hidePrompt: () => call("prompt_hide"),
  launchInfo,
};
