// Speech output through the operating system's voices (Web Speech API in the webview).
// Only languages with an installed voice are offered; nothing is faked.
import { SPEECH_TAGS, type Language } from "./contracts";

type Listener = (speaking: boolean) => void;
const listeners = new Set<Listener>();
let speaking = false;

function setSpeaking(value: boolean) {
  speaking = value;
  listeners.forEach((l) => l(value));
}

export function onSpeakingChange(listener: Listener): () => void {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

export function isSpeaking(): boolean {
  return speaking;
}

function synth(): SpeechSynthesis | null {
  return typeof window !== "undefined" && "speechSynthesis" in window ? window.speechSynthesis : null;
}

export function voiceFor(language: Language): SpeechSynthesisVoice | null {
  const s = synth();
  if (!s) return null;
  const voices = s.getVoices();
  for (const tag of SPEECH_TAGS[language]) {
    const lower = tag.toLowerCase();
    const match = voices.find((v) => v.lang.toLowerCase() === lower || v.lang.toLowerCase().startsWith(`${lower}-`));
    if (match) return match;
  }
  return null;
}

export function loadVoices(): Promise<void> {
  const s = synth();
  if (!s) return Promise.resolve();
  if (s.getVoices().length) return Promise.resolve();
  return new Promise((resolve) => {
    const done = () => resolve();
    s.addEventListener("voiceschanged", done, { once: true });
    setTimeout(done, 1500);
  });
}

export function speak(text: string, language: Language): boolean {
  const s = synth();
  const voice = voiceFor(language);
  if (!s || !voice) return false;
  s.cancel();
  const utterance = new SpeechSynthesisUtterance(text);
  utterance.voice = voice;
  utterance.lang = voice.lang;
  utterance.onstart = () => setSpeaking(true);
  utterance.onend = () => setSpeaking(false);
  utterance.onerror = () => setSpeaking(false);
  setSpeaking(true);
  s.speak(utterance);
  return true;
}

export function stopSpeaking() {
  synth()?.cancel();
  setSpeaking(false);
}
