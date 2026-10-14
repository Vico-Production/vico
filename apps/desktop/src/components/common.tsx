import { useEffect, useRef, type ReactNode } from "react";
import { LANGUAGE_NAMES, type Language, type LanguageCapability } from "../lib/contracts";

export function Drawer({
  title,
  onClose,
  children,
  testId,
}: {
  title: string;
  onClose: () => void;
  children: ReactNode;
  testId?: string;
}) {
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const previous = document.activeElement as HTMLElement | null;
    ref.current?.querySelector<HTMLElement>("button, input, select, textarea")?.focus();
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => {
      window.removeEventListener("keydown", onKey);
      previous?.focus();
    };
  }, [onClose]);
  return (
    <div className="overlay" onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <div className="drawer" role="dialog" aria-modal="true" aria-label={title} ref={ref} data-testid={testId}>
        <header className="drawer-head">
          <h2>{title}</h2>
          <button className="btn ghost" onClick={onClose} aria-label={`Close ${title}`}>
            Close
          </button>
        </header>
        <div className="drawer-body">{children}</div>
      </div>
    </div>
  );
}

export function Toggle({
  label,
  description,
  checked,
  onChange,
  testId,
}: {
  label: string;
  description?: string;
  checked: boolean;
  onChange: (value: boolean) => void;
  testId?: string;
}) {
  return (
    <label className="toggle">
      <input
        type="checkbox"
        role="switch"
        checked={checked}
        onChange={(e) => onChange(e.target.checked)}
        data-testid={testId}
      />
      <span className="toggle-track" aria-hidden="true" />
      <span className="toggle-text">
        <strong>{label}</strong>
        {description && <small>{description}</small>}
      </span>
    </label>
  );
}

export function Notice({ kind, children }: { kind: "info" | "warn" | "error" | "ok"; children: ReactNode }) {
  return (
    <div className={`notice ${kind}`} role={kind === "error" ? "alert" : "status"}>
      {children}
    </div>
  );
}

const SPEECH_LABEL: Record<LanguageCapability["speech_label"], string> = {
  untested: "speech untested",
  beta: "speech beta",
  unreliable: "speech unreliable",
};

export function LanguagePicker({
  value,
  onChange,
  capabilities,
  label = "Language",
  disabled,
}: {
  value: Language;
  onChange: (lang: Language) => void;
  capabilities: LanguageCapability[];
  label?: string;
  disabled?: boolean;
}) {
  return (
    <div className="chips" role="radiogroup" aria-label={label}>
      {capabilities.map((cap) => (
        <button
          key={cap.code}
          role="radio"
          aria-checked={value === cap.code}
          className={`chip ${value === cap.code ? "active" : ""}`}
          onClick={() => onChange(cap.code)}
          disabled={disabled}
          title={cap.note || undefined}
          data-testid={`lang-${cap.code}`}
        >
          <span>{cap.name}</span>
          <small>
            {cap.experimental ? "experimental · " : ""}
            {SPEECH_LABEL[cap.speech_label]}
          </small>
        </button>
      ))}
    </div>
  );
}

export function LanguageSelect({
  value,
  onChange,
  label,
  id,
}: {
  value: Language;
  onChange: (lang: Language) => void;
  label: string;
  id: string;
}) {
  return (
    <label className="field" htmlFor={id}>
      <span>{label}</span>
      <select id={id} value={value} onChange={(e) => onChange(e.target.value as Language)}>
        {(Object.keys(LANGUAGE_NAMES) as Language[]).map((code) => (
          <option key={code} value={code}>
            {LANGUAGE_NAMES[code]}
          </option>
        ))}
      </select>
    </label>
  );
}
