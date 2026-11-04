import { useEffect, useState } from "react";
import { api, errorText, upload } from "../api";
import { datasetBackend, syncDataset } from "../sync";

interface FileInfo { name: string; size: number; modified: number }
interface Result {
  updated: number; unchanged: number; added: number; removed: number; kept_missing: number; unkeyed: number;
  new_columns: string[]; key: string; dry_run: boolean;
}

/**
 * Bestehende Liste aus einer neuen Version der Excel-Datei aktualisieren: Fortschritt bleibt erhalten,
 * geänderte Werte werden übernommen, neue Kabel ergänzt. Vorher zeigt eine Vorschau, was passiert.
 */
export function UpdateFromFile({ datasetId, projectId, columns, onDone, onClose }: {
  datasetId: number; projectId: number; columns: string[]; onDone?: () => void; onClose: () => void;
}) {
  const [files, setFiles] = useState<FileInfo[]>([]);
  const [file, setFile] = useState("");
  const [sheets, setSheets] = useState<string[]>([]);
  const [mode, setMode] = useState("first"); // first | all | sheet:<Name>
  const [key, setKey] = useState("");
  const [keepInputs, setKeepInputs] = useState(true);
  const [removeMissing, setRemoveMissing] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [preview, setPreview] = useState<Result | null>(null);
  const [done, setDone] = useState<Result | null>(null);

  const loadFiles = async (select?: string) => {
    const list = (await api<FileInfo[]>(`/api/projects/${projectId}/files`)).filter((f) => /\.(xlsx|xls|csv)$/i.test(f.name));
    setFiles(list);
    setFile((cur) => select ?? (list.some((f) => f.name === cur) ? cur : list[0]?.name ?? ""));
  };

  useEffect(() => {
    loadFiles().catch((e) => setError(errorText(e)));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    setPreview(null);
    setMode("first");
    if (!file || !/\.xlsx?$/i.test(file)) { setSheets([]); return; }
    api<{ sheets: string[] }>(`/api/projects/${projectId}/files/${encodeURIComponent(file)}/sheets`)
      .then((r) => setSheets(r.sheets)).catch(() => setSheets([]));
  }, [file, projectId]);

  const body = (dryRun: boolean) => ({
    file, dry_run: dryRun, key, keep_inputs: keepInputs, remove_missing: removeMissing,
    mode: mode.startsWith("sheet:") ? "sheet" : mode, sheet: mode.startsWith("sheet:") ? mode.slice(6) : "",
  });

  const run = async (dryRun: boolean) => {
    setBusy(true);
    setError("");
    try {
      const r = await api<Result>(`/api/datasets/${datasetId}/update`, { method: "POST", body: body(dryRun) });
      if (dryRun) { setPreview(r); setDone(null); return; }
      setDone(r);
      setPreview(null);
      await syncDataset(datasetBackend(datasetId)); // neue Zeilen und Farben sofort lokal holen
      onDone?.();
    } catch (e) {
      setError(errorText(e));
    } finally {
      setBusy(false);
    }
  };

  const onPick = async (picked: File | undefined) => {
    if (!picked) return;
    setBusy(true);
    setError("");
    try {
      const form = new FormData();
      form.append("file", picked);
      await upload(`/api/projects/${projectId}/files`, form);
      await loadFiles(picked.name);
    } catch (e) {
      setError(errorText(e));
    } finally {
      setBusy(false);
    }
  };

  const summary = (r: Result) => (
    <ul className="plain update-summary">
      <li><b>{r.updated}</b> Zeilen geändert, <b>{r.unchanged}</b> unverändert</li>
      <li><b>{r.added}</b> neue Zeilen{r.unkeyed ? ` (davon ${r.unkeyed} ohne Schlüsselwert)` : ""}</li>
      {removeMissing
        ? <li><b>{r.removed}</b> Zeilen entfernt (fehlen in der Datei)</li>
        : <li><b>{r.kept_missing}</b> Zeilen fehlen in der Datei und bleiben bestehen</li>}
      {r.new_columns.length > 0 && <li>Neue Spalten: {r.new_columns.join(", ")}</li>}
      <li className="muted">Zeilen erkannt über: {r.key ? `Spalte „${r.key}“` : "Reihenfolge in der Datei"}</li>
    </ul>
  );

  return (
    <fieldset className="card settings update-card">
      <legend>Liste aus Datei aktualisieren</legend>
      <p className="muted">
        Bestehende Kabel bleiben mit ihrem Fortschritt erhalten. Geänderte Werte aus der Datei werden übernommen, neue Zeilen ergänzt.
        Du kannst eine neue Version der Datei hier hochladen (gleicher Dateiname ersetzt die alte).
      </p>
      <div className="grid2">
        <label>Datei
          <select value={file} onChange={(e) => setFile(e.target.value)}>
            {files.map((f) => <option key={f.name} value={f.name}>{f.name}</option>)}
            {!files.length && <option value="">Keine Datei im Projekt</option>}
          </select>
        </label>
        <label>Neue Version hochladen
          <input type="file" accept=".xlsx,.xls,.csv" disabled={busy} onChange={(e) => { void onPick(e.target.files?.[0]); e.target.value = ""; }} />
        </label>
        {sheets.length > 1 && (
          <label>Blatt
            <select value={mode} onChange={(e) => { setMode(e.target.value); setPreview(null); }}>
              <option value="first">Erstes Blatt</option>
              <option value="all">Alle Blätter (wie beim Import „zu einer Liste“)</option>
              {sheets.map((s) => <option key={s} value={`sheet:${s}`}>Nur „{s}“</option>)}
            </select>
          </label>
        )}
        <label>Zeilen erkennen über
          <select value={key} onChange={(e) => { setKey(e.target.value); setPreview(null); }}>
            <option value="">Automatisch (Kabelnummer, sonst Reihenfolge)</option>
            {columns.map((c) => <option key={c} value={c}>{c}</option>)}
          </select>
        </label>
      </div>
      <label className="check"><input type="checkbox" checked={keepInputs} onChange={(e) => { setKeepInputs(e.target.checked); setPreview(null); }} />
        Eintragungen aus der App behalten (Von, Bis, gezogene Länge, Datum)</label>
      <label className="check"><input type="checkbox" checked={removeMissing} onChange={(e) => { setRemoveMissing(e.target.checked); setPreview(null); }} />
        Zeilen entfernen, die in der Datei nicht mehr vorkommen</label>
      <div className="row-buttons">
        <button disabled={busy || !file} onClick={() => void run(true)}>{busy ? "Bitte warten …" : "Vorschau"}</button>
        <button className="primary" disabled={busy || !file || !preview} onClick={() => void run(false)}
          title={preview ? "" : "Erst die Vorschau ansehen"}>Jetzt aktualisieren</button>
        <button onClick={onClose}>Schließen</button>
      </div>
      {preview && <div className="banner warn"><div><b>Vorschau – noch nichts geändert</b>{summary(preview)}</div></div>}
      {done && <div className="banner ok-banner"><div><b>Liste aktualisiert</b>{summary(done)}</div></div>}
      {error && <p className="error">{error}</p>}
      <p className="muted">Nur online möglich. Geräte, die gerade offline sind, bekommen die Änderungen beim nächsten Abgleich.</p>
    </fieldset>
  );
}
