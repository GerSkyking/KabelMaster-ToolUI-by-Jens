// Verlauf: wer hat wann welchen Wert geändert; ganze Läufe (Übersetzer) und einzelne Werte lassen sich zurücksetzen.
import { Fragment, useCallback, useEffect, useMemo, useState } from "react";
import { api, errorText } from "../api";
import { syncDataset } from "../sync";
import type { Backend } from "../sync";

interface Change {
  id: number; row_id: number; label: string; field: string; old: unknown; new: unknown; kind: string; by: string;
  at: string; batch: string | null;
}
interface HistoryPage { changes: Change[]; undone: string[]; next: number | null; total: number }
interface Entry { key: string; kind: string; by: string; at: string; batch: string | null; changes: Change[] }

const KIND: Record<string, string> = {
  edit: "Bearbeitet", translate: "Übersetzer", undo: "Rückgängig", resolve: "Konflikt entschieden", label: "Beschriftet",
  create: "Neue Zeile", delete: "Zeile gelöscht",
};
const FILTERS = [["all", "Alles"], ["edit", "Von Hand"], ["translate", "Übersetzer"], ["undo", "Rückgängig"]] as const;
const show = (v: unknown) => (v === null || v === undefined || v === "" ? "leer" : String(v));
const when = (iso: string) => new Date(iso).toLocaleString("de-DE", { dateStyle: "short", timeStyle: "medium" });

/** Fasst zusammen, was zusammengehört: einen Lauf, oder aufeinanderfolgende Änderungen derselben Zeile durch dieselbe Person. */
export function groupChanges(changes: Change[]): Entry[] {
  const out: Entry[] = [];
  for (const c of changes) {
    const last = out[out.length - 1];
    const same = last && (c.batch
      ? last.batch === c.batch
      : !last.batch && last.by === c.by && last.kind === c.kind && last.changes[0].row_id === c.row_id
        && Math.abs(new Date(last.at).getTime() - new Date(c.at).getTime()) < 120_000);
    if (same) last.changes.push(c);
    else out.push({ key: `${c.id}`, kind: c.kind, by: c.by, at: c.at, batch: c.batch, changes: [c] });
  }
  return out;
}

export function HistoryTab({ backend, datasetId }: { backend: Backend; datasetId: number }) {
  const [changes, setChanges] = useState<Change[]>([]);
  const [undone, setUndone] = useState<string[]>([]);
  const [next, setNext] = useState<number | null>(null);
  const [total, setTotal] = useState(0);
  const [filter, setFilter] = useState<(typeof FILTERS)[number][0]>("all");
  const [open, setOpen] = useState<string | null>(null);
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  const load = useCallback(async (before = 0) => {
    try {
      const page = await api<HistoryPage>(`/api/datasets/${datasetId}/history${before ? `?before=${before}` : ""}`);
      setChanges((prev) => (before ? [...prev, ...page.changes] : page.changes));
      setUndone(page.undone);
      setNext(page.next);
      setTotal(page.total);
    } catch (e) {
      setError(errorText(e));
    }
  }, [datasetId]);
  useEffect(() => void load(), [load]);

  const entries = useMemo(() => groupChanges(changes).filter((e) => filter === "all" || e.kind === filter), [changes, filter]);

  const act = async (path: string, ok: (r: { cells: number; skipped?: number }) => string) => {
    setBusy(true);
    setError("");
    setMessage("");
    try {
      const result = await api<{ cells: number; skipped?: number }>(`/api/datasets/${datasetId}/history/${path}`, { method: "POST" });
      setMessage(ok(result));
      await syncDataset(backend).catch(() => undefined);
      await load();
    } catch (e) {
      setError(errorText(e));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="tool">
      <section className="card">
        <div className="inline-form">
          <h3>Änderungsverlauf</h3>
          <span className="muted">{total} Änderung(en) insgesamt</span>
          <label>Anzeigen
            <select value={filter} onChange={(e) => setFilter(e.target.value as typeof filter)}>
              {FILTERS.map(([id, label]) => <option key={id} value={id}>{label}</option>)}
            </select>
          </label>
          <button onClick={() => void load()}>Aktualisieren</button>
        </div>
        {error && <p className="error">{error}</p>}
        {message && <p className="ok">{message}</p>}
        <div className="table-wrap tall">
          <table>
            <thead><tr><th>Zeit</th><th>Wer</th><th>Art</th><th>Was</th><th></th></tr></thead>
            <tbody>
              {entries.map((e) => {
                const isBatch = !!e.batch && e.kind !== "undo";
                const rows = new Set(e.changes.map((c) => c.row_id)).size;
                const done = isBatch && undone.includes(e.batch!);
                const expanded = open === e.key;
                const cells = e.changes.filter((c) => c.field !== "*");
                return (
                  <Fragment key={e.key}>
                    <tr>
                      <td>{when(e.at)}</td><td>{e.by}</td><td>{KIND[e.kind] ?? e.kind}</td>
                      <td>
                        {e.changes.length === 1 && e.changes[0].field !== "*" ? (
                          <><b>{e.changes[0].label}</b> · {e.changes[0].field}: <s className="muted">{show(e.changes[0].old)}</s> → <b>{show(e.changes[0].new)}</b></>
                        ) : e.changes[0].field === "*" ? <b>{e.changes[0].label}</b> : (
                          <>{cells.length} Zelle(n) in {rows} Zeile(n) <button className="link" onClick={() => setOpen(expanded ? null : e.key)}>{expanded ? "weniger" : "Details"}</button></>
                        )}
                      </td>
                      <td className="actions">
                        {isBatch && !done && <button disabled={busy} onClick={() => confirm("Diesen Lauf rückgängig machen? Werte, die danach erneut geändert wurden, bleiben unverändert.")
                          && void act(`batches/${e.batch}/undo`, (r) => `${r.cells} Zelle(n) zurückgesetzt${r.skipped ? `, ${r.skipped} übersprungen (inzwischen geändert)` : ""}.`)}>Lauf rückgängig</button>}
                        {done && <span className="chip">rückgängig gemacht</span>}
                        {!isBatch && e.changes.length === 1 && e.changes[0].field !== "*" && e.kind !== "undo" && (
                          <button disabled={busy} onClick={() => void act(`changes/${e.changes[0].id}/revert`, () => "Wert zurückgesetzt.")}>Zurücksetzen</button>
                        )}
                      </td>
                    </tr>
                    {expanded && (
                      <tr><td colSpan={5}>
                        <ul className="plain">
                          {cells.map((c) => (
                            <li key={c.id}>{c.label} · {c.field}: <s className="muted">{show(c.old)}</s> → <b>{show(c.new)}</b></li>
                          ))}
                        </ul>
                      </td></tr>
                    )}
                  </Fragment>
                );
              })}
              {!entries.length && <tr><td colSpan={5} className="muted">Keine Einträge.</td></tr>}
            </tbody>
          </table>
        </div>
        {next !== null && <button onClick={() => void load(next)}>Ältere laden</button>}
      </section>
    </div>
  );
}
