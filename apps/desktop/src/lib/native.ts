// Show and hide Vico's windows. No-ops in the browser preview.
import { inTauri } from "./bus";

async function call(command: string): Promise<void> {
  if (!inTauri) return;
  const { invoke } = await import("@tauri-apps/api/core");
  await invoke(command).catch(() => undefined);
}

export interface Native {
  showAura(): Promise<void>;
  hideAura(): Promise<void>;
  showPrompt(): Promise<void>;
  hidePrompt(): Promise<void>;
}

export const native: Native = {
  showAura: () => call("aura_show"),
  hideAura: () => call("aura_hide"),
  showPrompt: () => call("prompt_show"),
  hidePrompt: () => call("prompt_hide"),
};
