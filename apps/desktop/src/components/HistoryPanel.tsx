import { useEffect, useState } from "react";
import { api, errorMessage } from "../lib/api";
import type { HistoryEntry } from "../lib/contracts";
import { Drawer, Notice } from "./common";

const OUTCOME: Record<string, string> = {
  succeeded: "Done · verified",
  unverified: "Done · not verified",
  failed: "Failed",
  denied: "Blocked",
  rejected: "Declined",
};

export function HistoryPanel({ onClose }: { onClose: () => void }) {
  const [items, setItems] = useState<HistoryEntry[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [confirming, setConfirming] = useState(false);

  const load = () =>
    api
      .history()
      .then(setItems)
      .catch((err) => setError(errorMessage(err)));

  useEffect(() => {
    void load();
  }, []);

  const clear = async () => {
    try {
      await api.clearHistory();
      setConfirming(false);
      await load();
    } catch (err) {
      setError(errorMessage(err));
    }
  };

  return (
    <Drawer title="Activity history" onClose={onClose} testId="history">
      <p className="muted small">
        Vico keeps the time, language, a short description, the tool, your approval and the verified result. It does not
        keep audio, file contents or full transcripts.
      </p>
      {error && <Notice kind="error">{error}</Notice>}
      {items && items.length === 0 && <p>No activity yet.</p>}
      {items && items.length > 0 && (
        <>
          <ul className="history">
            {items.map((item) => (
              <li key={item.id} className={`history-item ${item.outcome}`}>
                <div className="row spread">
                  <strong>{item.summary}</strong>
                  <span className={`badge ${item.outcome}`}>{OUTCOME[item.outcome] ?? item.outcome}</span>
                </div>
                <small className="muted">
                  {new Date(item.created_at).toLocaleString()} · {item.language} · {item.tool} · approval: {item.approval}
                </small>
                {item.detail && <p className="small">{item.detail}</p>}
              </li>
            ))}
          </ul>
          {confirming ? (
            <div className="row">
              <span>Delete all history?</span>
              <button className="btn danger" onClick={clear} data-testid="confirm-clear">
                Delete
              </button>
              <button className="btn" onClick={() => setConfirming(false)}>
                Keep
              </button>
            </div>
          ) : (
            <button className="btn" onClick={() => setConfirming(true)} data-testid="clear-history">
              Clear history
            </button>
          )}
        </>
      )}
    </Drawer>
  );
}
