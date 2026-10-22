// Konflikte: zwei Personen haben dasselbe Feld unterschiedlich geändert - hier wird entschieden.
import { useCallback, useEffect, useState } from "react";
import { api, errorText } from "../api";
import { syncDataset } from "../sync";
import type { Backend } from "../sync";

export interface ConflictItem {
  id: number; dataset_id: number; dataset_name: string; row_number: number | null; label: string; field: string;
  base_value: unknown; server_value: unknown; server_by: string; server_at: string | null;
  proposed_value: unknown; proposed_by: string; proposed_at: string;
}

const show = (v: unknown) => (v === null || v === undefined || v === "" ? "leer" : String(v));
const when = (iso: string | null) => (iso ? new Date(iso).toLocaleString("de-DE") : "");

export function ConflictList({ items, onResolve, showDataset }: {
  items: ConflictItem[]; onResolve: (c: ConflictItem, choice: "server" | "proposed") => void; showDataset?: boolean;
}) {
  if (!items.length) return <p className="muted">Keine offenen Konflikte.</p>;
  return (
    <ul className="plain conflicts">
      {items.map((c) => (
        <li key={c.id} className="card">
          <b>{showDataset ? `${c.dataset_name} · ` : ""}{c.label || `Zeile ${c.row_number}`}</b> · Feld „{c.field}“ <span className="muted">(vorher: {show(c.base_value)})</span>
          <div className="choice">
            <div>
              <div className="muted">Aktuell im System – {c.server_by || "?"}, {when(c.server_at)}</div>
              <b className="value">{show(c.server_value)}</b>
              <button onClick={() => onResolve(c, "server")}>Diesen Wert behalten</button>
            </div>
            <div>
              <div className="muted">Vorschlag von {c.proposed_by}, {when(c.proposed_at)}</div>
              <b className="value">{show(c.proposed_value)}</b>
              <button className="primary" onClick={() => onResolve(c, "proposed")}>Diesen Wert übernehmen</button>
            </div>
          </div>
        </li>
      ))}
    </ul>
  );
}

export function ConflictsTab({ backend, datasetId }: { backend: Backend; datasetId: number }) {
  const [items, setItems] = useState<ConflictItem[]>([]);
  const [error, setError] = useState("");
  const load = useCallback(async () => {
    try {
      setItems(await api<ConflictItem[]>(`/api/datasets/${datasetId}/conflicts`));
    } catch (e) {
      setError(errorText(e));
    }
  }, [datasetId]);
  useEffect(() => void load(), [load]);

  const resolve = async (c: ConflictItem, choice: "server" | "proposed") => {
    setError("");
    try {
      await api(`/api/conflicts/${c.id}/resolve`, { method: "POST", body: { choice } });
      await syncDataset(backend).catch(() => undefined);
      await load();
    } catch (e) {
      setError(errorText(e));
    }
  };
  return (
    <div className="tool">
      {error && <div className="banner error">{error}</div>}
      <p className="muted">Ändern zwei Personen dasselbe Feld, bleibt zunächst der Wert im System stehen. Hier entscheidet jemand, welcher Wert gilt.</p>
      <ConflictList items={items} onResolve={(c, ch) => void resolve(c, ch)} />
    </div>
  );
}
