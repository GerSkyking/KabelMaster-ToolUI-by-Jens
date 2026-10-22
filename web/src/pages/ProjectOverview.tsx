// Projekt-Übersicht: Stand je Liste und Querschnitt, offene Konflikte, Tagesbericht.
import { useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api, errorText, fetchGet, saveBlob } from "../api";
import { ConflictItem, ConflictList } from "../tools/ConflictsTab";
import { DatasetOverview, OverviewTable } from "../tools/OverviewTab";

export function ProjectOverview({ projectId, canEdit }: { projectId: number; canEdit: boolean }) {
  const [data, setData] = useState<{ datasets: DatasetOverview[]; conflicts: number } | null>(null);
  const [conflicts, setConflicts] = useState<ConflictItem[]>([]);
  const [error, setError] = useState("");
  const [start, setStart] = useState("");
  const [end, setEnd] = useState("");

  const load = useCallback(async () => {
    try {
      setData(await api(`/api/projects/${projectId}/overview`));
      setConflicts(await api<ConflictItem[]>(`/api/projects/${projectId}/conflicts`));
    } catch (e) {
      setError(errorText(e));
    }
  }, [projectId]);
  useEffect(() => void load(), [load]);

  const resolve = async (c: ConflictItem, choice: "server" | "proposed") => {
    try {
      await api(`/api/conflicts/${c.id}/resolve`, { method: "POST", body: { choice } });
      await load();
    } catch (e) {
      setError(errorText(e));
    }
  };
  const report = async () => {
    try {
      const query = new URLSearchParams({ ...(start ? { start } : {}), ...(end ? { end } : {}) }).toString();
      saveBlob(await fetchGet(`/api/projects/${projectId}/report.txt${query ? `?${query}` : ""}`, "Tagesbericht.txt"));
    } catch (e) {
      setError(errorText(e));
    }
  };

  if (!data) return error ? <p className="error">{error}</p> : null;
  return (
    <section className="card">
      <h2>Übersicht</h2>
      {error && <p className="error">{error}</p>}
      {data.datasets.map((d) => (
        <div key={d.id}>
          <h3><Link to={`/datasets/${d.id}?tab=overview`}>{d.name}</Link>{d.conflicts > 0 && <Link className="badge" to={`/datasets/${d.id}?tab=conflicts`}>{d.conflicts} Konflikt(e)</Link>}</h3>
          <OverviewTable overview={d} />
        </div>
      ))}
      {!data.datasets.length && <p className="muted">Noch keine Liste importiert.</p>}
      <div className="inline-form">
        <label>Tagesbericht von<input type="date" value={start} onChange={(e) => setStart(e.target.value)} /></label>
        <label>bis<input type="date" value={end} onChange={(e) => setEnd(e.target.value)} /></label>
        <button onClick={() => void report()}>TXT-Bericht (alle Listen)</button>
      </div>
      {conflicts.length > 0 && (
        <>
          <h3>Offene Konflikte ({conflicts.length})</h3>
          {canEdit ? <ConflictList showDataset items={conflicts} onResolve={(c, ch) => void resolve(c, ch)} />
            : <p className="muted">Zum Entscheiden wird die Rolle „Bearbeiter“ benötigt.</p>}
        </>
      )}
    </section>
  );
}
