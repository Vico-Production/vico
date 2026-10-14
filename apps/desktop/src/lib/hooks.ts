import { useCallback, useEffect, useRef, useState } from "react";
import { api, errorMessage } from "./api";
import { TERMINAL_STATES, type AudioStatus, type Language, type Run, type Transcript } from "./contracts";
import { isSpeaking, onSpeakingChange } from "./speech";

export type MicPhase = "idle" | "starting" | "listening" | "processing";

/** Push-to-talk recording through the sidecar. Never records while speech is playing. */
export function useRecorder(onTranscript: (t: Transcript) => void) {
  const [phase, setPhase] = useState<MicPhase>("idle");
  const [status, setStatus] = useState<AudioStatus | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [speaking, setSpeaking] = useState(isSpeaking());
  const timer = useRef<number | null>(null);
  const stopping = useRef(false);
  const callback = useRef(onTranscript);
  callback.current = onTranscript;

  useEffect(() => onSpeakingChange(setSpeaking), []);

  const clearTimer = () => {
    if (timer.current !== null) window.clearInterval(timer.current);
    timer.current = null;
  };

  const stop = useCallback(async () => {
    if (stopping.current) return;
    stopping.current = true;
    clearTimer();
    setPhase("processing");
    try {
      const result = await api.stopRecording(true);
      if (result.transcript) callback.current(result.transcript);
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setPhase("idle");
      setStatus(null);
      stopping.current = false;
    }
  }, []);

  const start = useCallback(
    async (language: Language) => {
      if (isSpeaking()) {
        setError("Wait for the spoken answer to finish before recording.");
        return;
      }
      setError(null);
      setPhase("starting");
      try {
        setStatus(await api.startRecording(language));
        setPhase("listening");
        timer.current = window.setInterval(async () => {
          try {
            const s = await api.recordingStatus();
            setStatus(s);
            if (s.full || s.elapsed_s >= s.max_s) void stop();
          } catch {
            /* polling errors surface on stop */
          }
        }, 250);
      } catch (err) {
        setError(errorMessage(err));
        setPhase("idle");
      }
    },
    [stop],
  );

  const cancel = useCallback(async () => {
    clearTimer();
    try {
      await api.cancelRecording();
    } finally {
      setPhase("idle");
      setStatus(null);
    }
  }, []);

  useEffect(
    () => () => {
      clearTimer();
      void api.cancelRecording().catch(() => undefined);
    },
    [],
  );

  return { phase, status, error, setError, start, stop, cancel, blocked: speaking };
}

/** Poll an agent run until it reaches a terminal state. */
export function useRun() {
  const [run, setRun] = useState<Run | null>(null);
  const [error, setError] = useState<string | null>(null);
  const runId = run?.id;
  const state = run?.state;

  useEffect(() => {
    if (!runId || !state || TERMINAL_STATES.includes(state)) return;
    let alive = true;
    const id = window.setInterval(async () => {
      try {
        const next = await api.getRun(runId);
        if (alive) setRun(next);
      } catch (err) {
        if (alive) setError(errorMessage(err));
      }
    }, 400);
    return () => {
      alive = false;
      window.clearInterval(id);
    };
  }, [runId, state]);

  const guard = useCallback(async (fn: () => Promise<Run>) => {
    setError(null);
    try {
      setRun(await fn());
    } catch (err) {
      setError(errorMessage(err));
    }
  }, []);

  return { run, setRun, error, setError, guard };
}

export function useInterval(fn: () => void, ms: number) {
  const saved = useRef(fn);
  saved.current = fn;
  useEffect(() => {
    saved.current();
    const id = window.setInterval(() => saved.current(), ms);
    return () => window.clearInterval(id);
  }, [ms]);
}
