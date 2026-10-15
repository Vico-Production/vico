import { useCallback, useEffect, useMemo, useState } from "react";
import { emit, listen } from "../lib/bus";
import { INITIAL, INTENT_EVENT, STATE_EVENT, VicoDriver, type Intent, type Session } from "../lib/session";
import { Aura } from "./Aura";
import { Prompt } from "./Prompt";

function useDriver(driver: VicoDriver): Session {
  const [session, setSession] = useState<Session>(driver.state);
  useEffect(() => driver.subscribe(setSession), [driver]);
  return session;
}

/** Desktop aura window: hosts the driver and draws the full-screen effect. */
export function AuraWindow() {
  const driver = useMemo(() => new VicoDriver(), []);
  const session = useDriver(driver);
  useEffect(() => {
    const stops = [
      listen<Intent>(INTENT_EVENT, (intent) => driver.dispatch(intent)),
      listen<null>("vico://summon", () => driver.dispatch({ type: "summon" })),
      listen<null>("vico://settings", () => driver.dispatch({ type: "settings" })),
    ];
    void driver.boot();
    return () => stops.forEach((stop) => stop());
  }, [driver]);
  return <Aura session={session} />;
}

/** Desktop prompt window: mirrors the driver's state and sends back what the user does. */
export function PromptWindow() {
  const [session, setSession] = useState<Session>(INITIAL);
  useEffect(() => {
    const stop = listen<Session>(STATE_EVENT, setSession);
    void emit<Intent>(INTENT_EVENT, { type: "hello" });
    return stop;
  }, []);
  const send = useCallback((intent: Intent) => void emit(INTENT_EVENT, intent), []);
  return <Prompt session={session} send={send} />;
}

/** Browser preview: both layers in one page over a stand-in desktop. */
export function Stage() {
  const driver = useMemo(() => new VicoDriver(), []);
  const session = useDriver(driver);
  const send = useCallback((intent: Intent) => driver.dispatch(intent), [driver]);
  useEffect(() => {
    void driver.boot();
    const onKey = (e: KeyboardEvent) => {
      // Win+Alt+V cannot be captured in a browser; the preview uses Ctrl+Alt+V.
      if (e.ctrlKey && e.altKey && e.key.toLowerCase() === "v") {
        e.preventDefault();
        driver.dispatch({ type: "summon" });
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [driver]);
  return (
    <div className="stage" data-testid="stage">
      <div className="desk" aria-hidden="true">
        <div className="desk-window a" />
        <div className="desk-window b" />
        <div className="desk-bar" />
      </div>
      {session.phase === "hidden" && (
        <button className="summon-hint" onClick={() => driver.dispatch({ type: "summon" })} data-testid="summon">
          Press <kbd>Ctrl</kbd> + <kbd>Alt</kbd> + <kbd>V</kbd> to summon Vico
          <small>(Win + Alt + V in the desktop app)</small>
        </button>
      )}
      <Aura session={session} />
      <div className={`stage-prompt ${session.phase === "hidden" ? "" : "on"}`}>
        <Prompt session={session} send={send} />
      </div>
    </div>
  );
}
