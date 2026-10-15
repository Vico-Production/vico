// Messages between Vico's two windows. In the desktop app these are Tauri events;
// in the browser preview both views live in one page and share a local event target.

export const inTauri = typeof window !== "undefined" && "__TAURI_INTERNALS__" in window;

const local = new EventTarget();

export async function emit<T>(event: string, payload: T): Promise<void> {
  if (inTauri) {
    const { emit: tauriEmit } = await import("@tauri-apps/api/event");
    await tauriEmit(event, payload);
    return;
  }
  local.dispatchEvent(new CustomEvent(event, { detail: payload }));
}

export function listen<T>(event: string, handler: (payload: T) => void): () => void {
  if (inTauri) {
    let stop: (() => void) | null = null;
    let disposed = false;
    void import("@tauri-apps/api/event").then(({ listen: tauriListen }) =>
      tauriListen<T>(event, (e) => handler(e.payload)).then((unlisten) => {
        if (disposed) unlisten();
        else stop = unlisten;
      }),
    );
    return () => {
      disposed = true;
      stop?.();
    };
  }
  const fn = (e: Event) => handler((e as CustomEvent<T>).detail);
  local.addEventListener(event, fn);
  return () => local.removeEventListener(event, fn);
}

/** Which Vico surface this page is: the full-screen aura, the prompt, or the browser preview. */
export async function currentView(): Promise<"aura" | "prompt" | "stage"> {
  if (inTauri) {
    const { getCurrentWindow } = await import("@tauri-apps/api/window");
    const label = getCurrentWindow().label;
    return label === "prompt" ? "prompt" : "aura";
  }
  const view = new URLSearchParams(window.location.search).get("view");
  return view === "aura" || view === "prompt" ? view : "stage";
}
