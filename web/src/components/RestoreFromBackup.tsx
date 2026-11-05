import { useState } from "react";
import { errorText, upload } from "../api";
import { syncDataset, datasetBackend } from "../sync";

/** Auswahl der Spalten, die übernommen werden sollen. Nichts angehakt = alle Spalten. */
export function ColumnPicker({ columns, value, onChange }: { columns: string[]; value: string[]; onChange: (v: string[]) => void }) {
  const toggle = (c: string) => onChange(value.includes(c) ? value.filter((x) => x !== c) : [...value, c]);
  return (
    <details className="column-pick">
      <summary>{value.length ? `${value.length} von ${columns.length} Spalten ausgewählt` : "Alle Spalten"} – Auswahl ändern</summary>
      <div className="row-buttons">
        <button type="button" onClick={() => onChange([])}>Alle Spalten</button>
        <button type="button" onClick={() => onChange([...columns])}>Alle anhaken</button>
      </div>
      <div className="column-pick-list">
        {columns.map((c) => (
          <label key={c} className="check"><input type="checkbox" checked={value.includes(c)} onChange={() => toggle(c)} />{c}</label>
        ))}
      </div>
      <p className="muted">Ohne Haken werden alle Spalten übernommen. Mit Auswahl ändert sich nur der Inhalt dieser Spalten.</p>
    </details>
  );
}

interface Option { ref: string; project: string; dataset: string; rows: number }
interface Preview {
  options: Option[]; source: string; found: boolean; created?: string; applied: boolean; columns?: string[];
  diff?: { rows_now: number; rows_backup: number; changed_cells: number; added: number; removed: number; columns_added: string[]; columns_removed: string[] };
  result?: { rows: number };
}

/** Diese Liste aus einem heruntergeladenen Backup (ZIP) zurückholen, komplett oder nur bestimmte Spalten. */
export function RestoreFromBackup({ datasetId, columns, onDone }: { datasetId: number; columns: string[]; onDone?: () => void }) {
  const [file, setFile] = useState<File | null>(null);
  const [source, setSource] = useState("");
  const [only, setOnly] = useState<string[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [data, setData] = useState<Preview | null>(null);

  const call = async (apply: boolean, src = source, f = file) => {
    if (!f) return;
    setBusy(true);
    setError("");
    try {
      const form = new FormData();
      form.append("file", f);
      form.append("source", src);
      form.append("apply", apply ? "true" : "false");
      if (only.length) form.append("only_columns", JSON.stringify(only));
      const r = await upload<Preview>(`/api/datasets/${datasetId}/restore`, form);
      setData(r);
      if (apply) {
        await syncDataset(datasetBackend(datasetId));
        onDone?.();
      }
    } catch (e) {
      setError(errorText(e));
    } finally {
      setBusy(false);
    }
  };

  const pick = (f: File | undefined) => {
    setFile(f ?? null);
    setData(null);
    setSource("");
    if (f) void call(false, "", f);
  };

  const d = data?.diff;
  return (
    <fieldset className="card settings update-card">
      <legend>Aus Backup wiederherstellen</legend>
      <p className="muted">
        Lade ein heruntergeladenes Backup (ZIP) hoch. Nur diese Liste wird zurückgeholt; vorher wird das Projekt automatisch gesichert.
      </p>
      <label>Backup-Datei (.zip)
        <input type="file" accept=".zip" disabled={busy} onChange={(e) => { pick(e.target.files?.[0]); e.target.value = ""; }} />
      </label>
      {data && (
        <>
          <label>Liste im Backup
            <select value={data.source} onChange={(e) => { setSource(e.target.value); void call(false, e.target.value); }}>
              {!data.options.some((o) => o.ref === data.source) && <option value={data.source}>– bitte wählen –</option>}
              {data.options.map((o) => <option key={o.ref} value={o.ref}>{o.project} / {o.dataset} ({o.rows} Zeilen)</option>)}
            </select>
          </label>
          {data.found && <ColumnPicker columns={data.columns ?? columns} value={only} onChange={(v) => { setOnly(v); setData({ ...data, applied: false, diff: undefined }); }} />}
        </>
      )}
      {!data?.found && data && <p className="muted">In diesem Backup gibt es keine Liste mit gleichem Namen. Bitte oben eine auswählen.</p>}
      <div className="row-buttons">
        <button disabled={busy || !file} onClick={() => void call(false)}>{busy ? "Bitte warten …" : "Vorschau"}</button>
        <button className="primary" disabled={busy || !data?.found || data.applied}
          onClick={() => confirm("Liste jetzt aus dem Backup wiederherstellen? Der aktuelle Stand wird vorher automatisch gesichert.") && void call(true)}>
          Jetzt wiederherstellen
        </button>
      </div>
      {d && !data?.applied && (
        <div className="banner warn"><div>
          <b>Vorschau – noch nichts geändert</b>
          <ul className="plain update-summary">
            <li>Backup vom {data?.created ? new Date(data.created).toLocaleString("de-DE") : "unbekannt"}</li>
            <li><b>{d.changed_cells}</b> Zellen würden sich ändern</li>
            {only.length === 0 && <li><b>{d.added}</b> Zeilen kämen zurück, <b>{d.removed}</b> Zeilen würden entfernt (jetzt {d.rows_now}, im Backup {d.rows_backup})</li>}
            {d.columns_added.length > 0 && <li>Spalten kämen zurück: {d.columns_added.join(", ")}</li>}
            {only.length === 0 && d.columns_removed.length > 0 && <li>Spalten würden entfallen: {d.columns_removed.join(", ")}</li>}
          </ul>
        </div></div>
      )}
      {data?.applied && <div className="banner ok-banner"><div><b>Wiederhergestellt</b> – {data.result?.rows ?? 0} Zeilen.</div></div>}
      {error && <p className="error">{error}</p>}
    </fieldset>
  );
}
