// Sicherungen: erstellen, herunterladen, hochladen, Versionen vergleichen, Projekt wiederherstellen.
import { useCallback, useEffect, useState } from "react";
import { api, errorText, fetchGet, saveBlob } from "../api";

interface BackupInfo { id: number; filename: string; kind: string; created_by: string; created_at: string; size: number; summary: { projects: number; datasets: number; rows: number; templates: number } }
interface Schedule { enabled: boolean; time: string; keep: number; include_files: boolean }
interface Diff {
  datasets: { project: string; dataset: string; rows_added: number; rows_removed: number; changed_cells: number; columns_added: string[]; columns_removed: string[]; changes: { row: number; field: string; old: unknown; new: unknown }[] }[];
  added_datasets: string[]; removed_datasets: string[]; truncated: boolean; totals: { added: number; removed: number; changed_cells: number };
}

const KIND: Record<string, string> = { manual: "manuell", auto: "automatisch", "pre-restore": "vor Wiederherstellung", upload: "hochgeladen" };
const kb = (n: number) => (n > 1e6 ? `${(n / 1e6).toFixed(1)} MB` : `${Math.ceil(n / 1e3)} kB`);
const val = (v: unknown) => (v === null || v === undefined || v === "" ? "leer" : String(v));

export function BackupsPanel() {
  const [items, setItems] = useState<BackupInfo[]>([]);
  const [schedule, setSchedule] = useState<Schedule | null>(null);
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");
  const [a, setA] = useState("");
  const [b, setB] = useState("current");
  const [diff, setDiff] = useState<Diff | null>(null);
  const [withFiles, setWithFiles] = useState(false);
  const [slug, setSlug] = useState("");

  const load = useCallback(async () => {
    try {
      const r = await api<{ backups: BackupInfo[]; schedule: Schedule }>("/api/admin/backups");
      setItems(r.backups);
      setSchedule(r.schedule);
    } catch (e) {
      setError(errorText(e));
    }
  }, []);
  useEffect(() => void load(), [load]);

  const run = async (action: () => Promise<unknown>, ok = "") => {
    setError("");
    setMessage("");
    try {
      await action();
      if (ok) setMessage(ok);
      await load();
    } catch (e) {
      setError(errorText(e));
    }
  };

  const compare = () => run(async () => {
    setDiff(await api<Diff>("/api/admin/backups/compare", { method: "POST", body: { old: Number(a), new: b === "current" ? null : Number(b) } }));
  });
  const restore = (id: number) => {
    if (!slug.trim()) return setError("Bitte das Projektkürzel (Slug) angeben, das wiederhergestellt werden soll.");
    if (!confirm(`Projekt „${slug}“ aus dieser Sicherung wiederherstellen? Der aktuelle Stand wird vorher automatisch gesichert.`)) return;
    void run(async () => {
      const r = await api<{ rows: number }>(`/api/admin/backups/${id}/restore`, { method: "POST", body: { project: slug.trim() } });
      setMessage(`${r.rows} Zeilen wiederhergestellt.`);
    });
  };
  const upload = (file: File | undefined) => {
    if (!file) return;
    const form = new FormData();
    form.append("file", file);
    void run(() => api("/api/admin/backups/upload", { method: "POST", form }), `${file.name} hochgeladen.`);
  };

  return (
    <section className="card">
      <h2>Sicherungen</h2>
      {error && <p className="error">{error}</p>}
      {message && <p className="ok">{message}</p>}
      {schedule && (
        <p className="muted">
          Automatisch: {schedule.enabled ? `täglich ab ${schedule.time} Uhr, die letzten ${schedule.keep} werden behalten${schedule.include_files ? ", inkl. Dateien" : ""}` : "ausgeschaltet"}
          {" "}(Einstellung über BACKUP_* in der .env).
        </p>
      )}
      <div className="inline-form">
        <label className="check"><input type="checkbox" checked={withFiles} onChange={(e) => setWithFiles(e.target.checked)} />Excel-Dateien mitsichern</label>
        <button className="primary" onClick={() => void run(() => api("/api/admin/backups", { method: "POST", body: { include_files: withFiles } }), "Sicherung erstellt.")}>Jetzt sichern</button>
        <label className="upload-inline">Sicherung hochladen<input type="file" accept=".zip" onChange={(e) => { upload(e.target.files?.[0]); e.target.value = ""; }} /></label>
        <input placeholder="Projektkürzel für Wiederherstellung" value={slug} onChange={(e) => setSlug(e.target.value)} />
      </div>
      <div className="table-wrap tall">
        <table>
          <thead><tr><th>Zeit</th><th>Art</th><th>Von</th><th>Inhalt</th><th>Größe</th><th /></tr></thead>
          <tbody>
            {items.map((x) => (
              <tr key={x.id}>
                <td>{new Date(x.created_at).toLocaleString("de-DE")}</td><td>{KIND[x.kind] ?? x.kind}</td><td>{x.created_by}</td>
                <td>{x.summary.projects} Projekte, {x.summary.datasets} Listen, {x.summary.rows} Zeilen</td><td>{kb(x.size)}</td>
                <td className="actions">
                  <button onClick={() => void run(async () => saveBlob(await fetchGet(`/api/admin/backups/${x.id}/download`, x.filename)))}>Download</button>
                  <button onClick={() => restore(x.id)}>Wiederherstellen</button>
                  <button className="danger" onClick={() => confirm("Sicherung löschen?") && void run(() => api(`/api/admin/backups/${x.id}`, { method: "DELETE" }))}>Löschen</button>
                </td>
              </tr>
            ))}
            {!items.length && <tr><td className="muted">Noch keine Sicherung.</td></tr>}
          </tbody>
        </table>
      </div>

      <h3>Versionen vergleichen</h3>
      <div className="inline-form">
        <select value={a} onChange={(e) => setA(e.target.value)}>
          <option value="">Älterer Stand …</option>
          {items.map((x) => <option key={x.id} value={x.id}>{new Date(x.created_at).toLocaleString("de-DE")} ({KIND[x.kind] ?? x.kind})</option>)}
        </select>
        <span>mit</span>
        <select value={b} onChange={(e) => setB(e.target.value)}>
          <option value="current">aktuellem Stand</option>
          {items.map((x) => <option key={x.id} value={x.id}>{new Date(x.created_at).toLocaleString("de-DE")} ({KIND[x.kind] ?? x.kind})</option>)}
        </select>
        <button disabled={!a} onClick={() => void compare()}>Vergleichen</button>
      </div>
      {diff && (
        <div>
          <p><b>{diff.totals.changed_cells}</b> Zellen geändert, <b>{diff.totals.added}</b> Zeilen neu, <b>{diff.totals.removed}</b> Zeilen entfernt.
            {diff.added_datasets.length > 0 && <> Neue Listen: {diff.added_datasets.join(", ")}.</>}
            {diff.removed_datasets.length > 0 && <> Entfernte Listen: {diff.removed_datasets.join(", ")}.</>}</p>
          {diff.datasets.map((d) => (
            <details key={`${d.project}/${d.dataset}`} open>
              <summary>{d.project} / {d.dataset} – {d.changed_cells} Änderungen, +{d.rows_added} / −{d.rows_removed} Zeilen
                {d.columns_added.length > 0 && `, neue Spalten: ${d.columns_added.join(", ")}`}</summary>
              <div className="table-wrap tall">
                <table>
                  <thead><tr><th>Zeile</th><th>Feld</th><th>Vorher</th><th>Nachher</th></tr></thead>
                  <tbody>{d.changes.map((c, i) => <tr key={i}><td>{c.row}</td><td>{c.field}</td><td>{val(c.old)}</td><td>{val(c.new)}</td></tr>)}</tbody>
                </table>
              </div>
            </details>
          ))}
          {diff.truncated && <p className="muted">Anzeige auf 1000 Änderungen begrenzt.</p>}
          {!diff.datasets.length && <p className="muted">Keine Unterschiede.</p>}
        </div>
      )}
    </section>
  );
}
