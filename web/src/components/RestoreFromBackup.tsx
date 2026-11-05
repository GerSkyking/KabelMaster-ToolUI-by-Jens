import { useEffect, useState } from "react";
import { api, errorText, saveBlob, upload } from "../api";
import { syncDataset, datasetBackend } from "../sync";

/** Auswahl der Spalten, die übernommen werden sollen. Nichts angehakt = alle Spalten. */
export function ColumnPicker({ columns, value, onChange, presets = [] }: {
  columns: string[]; value: string[]; onChange: (v: string[]) => void; presets?: { label: string; columns: string[] }[];
}) {
  const toggle = (c: string) => onChange(value.includes(c) ? value.filter((x) => x !== c) : [...value, c]);
  return (
    <details className="column-pick">
      <summary>{value.length ? `${value.length} von ${columns.length} Spalten ausgewählt` : "Alle Spalten"} – Auswahl ändern</summary>
      <div className="row-buttons">
        <button type="button" onClick={() => onChange([])}>Alle Spalten</button>
        <button type="button" onClick={() => onChange([...columns])}>Alle anhaken</button>
        {presets.map((p) => <button key={p.label} type="button" onClick={() => onChange(p.columns)}>{p.label}</button>)}
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
  diff?: { items?: { idx: number; kind: "changed" | "added" | "removed"; label: string; columns: string[] }[]; items_total?: number; rows_now: number; rows_backup: number; changed_cells: number; added: number; removed: number; columns_added: string[]; columns_removed: string[] };
  result?: { rows: number; added?: number; removed?: number };
}

/** Diese Liste aus einem heruntergeladenen Backup (ZIP) zurückholen, komplett oder nur bestimmte Spalten. */
export function RestoreFromBackup({ datasetId, columns, onDone }: { datasetId: number; columns: string[]; onDone?: () => void }) {
  const [file, setFile] = useState<File | null>(null);
  const [source, setSource] = useState("");
  const [only, setOnly] = useState<string[]>([]);
  const [update, setUpdate] = useState(true);
  const [addRows, setAddRows] = useState(true);
  const [removeRows, setRemoveRows] = useState(true);
  const [presets, setPresets] = useState<{ label: string; columns: string[] }[]>([]);
  const [skip, setSkip] = useState<number[]>([]); // einzeln abgewählte Zeilen
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [data, setData] = useState<Preview | null>(null);

  useEffect(() => {
    // Schnellauswahl „Von / Bis“ aus der Spaltenzuordnung der Liste
    api<{ settings?: { mapping?: Record<string, string | undefined> } }>(`/api/datasets/${datasetId}`).then((d) => {
      const m = d.settings?.mapping ?? {};
      const pick = (...keys: string[]) => keys.map((k) => m[k]).filter((c): c is string => !!c && columns.includes(c));
      const vonBis = pick("start", "end");
      setPresets(vonBis.length ? [{ label: "Nur Von / Bis", columns: vonBis }] : []);
    }).catch(() => setPresets([]));
  }, [datasetId, columns]);

  const form = (f: File, src: string, apply: boolean) => {
    const fd = new FormData();
    fd.append("file", f);
    fd.append("source", src);
    fd.append("apply", apply ? "true" : "false");
    fd.append("update", String(update));
    fd.append("add_rows", String(addRows));
    fd.append("remove_rows", String(removeRows));
    const items = data?.diff?.items ?? [];
    if (skip.length && apply && items.length === data?.diff?.items_total) fd.append("only_rows", JSON.stringify(items.map((i) => i.idx).filter((i) => !skip.includes(i))));
    if (only.length) fd.append("only_columns", JSON.stringify(only));
    return fd;
  };

  const downloadList = async () => {
    if (!file) return;
    setBusy(true);
    setError("");
    try {
      const r = await fetch(`/api/datasets/${datasetId}/restore/export`, { method: "POST", body: form(file, data?.source ?? source, false), credentials: "same-origin" });
      if (!r.ok) throw new Error((await r.json().catch(() => ({ detail: r.statusText }))).detail);
      const m = /filename\*=UTF-8''([^;]+)/i.exec(r.headers.get("content-disposition") ?? "");
      saveBlob({ blob: await r.blob(), filename: m ? decodeURIComponent(m[1]) : "backup-liste.xlsx" });
    } catch (e) {
      setError(errorText(e));
    } finally {
      setBusy(false);
    }
  };

  const changed = () => { setSkip([]); setData((cur) => (cur ? { ...cur, applied: false, diff: undefined } : cur)); };

  const call = async (apply: boolean, src = source, f = file) => {
    if (!f) return;
    setBusy(true);
    setError("");
    try {
      const r = await upload<Preview>(`/api/datasets/${datasetId}/restore`, form(f, src, apply));
      setData(r);
      if (!apply) setSkip([]);
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
          {data.found && (
            <>
              <ColumnPicker columns={data.columns ?? columns} presets={presets} value={only} onChange={(v) => { setOnly(v); changed(); }} />
              <label className="check"><input type="checkbox" checked={update} onChange={(e) => { setUpdate(e.target.checked); changed(); }} />
                Werte in vorhandenen Zeilen auf den Stand des Backups setzen</label>
              <label className="check"><input type="checkbox" checked={addRows} onChange={(e) => { setAddRows(e.target.checked); changed(); }} />
                Zeilen ergänzen, die im Backup sind, aber jetzt fehlen</label>
              <label className="check"><input type="checkbox" checked={removeRows} onChange={(e) => { setRemoveRows(e.target.checked); changed(); }} />
                Zeilen entfernen, die es im Backup nicht gibt</label>
            </>
          )}
        </>
      )}
      {!data?.found && data && <p className="muted">In diesem Backup gibt es keine Liste mit gleichem Namen. Bitte oben eine auswählen.</p>}
      <div className="row-buttons">
        <button disabled={busy || !file} onClick={() => void call(false)}>{busy ? "Bitte warten …" : "Vorschau"}</button>
        <button disabled={busy || !data?.found} onClick={() => void downloadList()} title="Die Liste aus dem Backup als Excel-Datei laden">Liste als Excel laden</button>
        <button className="primary" disabled={busy || !data?.found || data.applied || (!update && !addRows && !removeRows) || (!!d && d.items?.length === d.items_total && skip.length === d.items?.length)}
          onClick={() => confirm("Liste jetzt aus dem Backup wiederherstellen? Der aktuelle Stand wird vorher automatisch gesichert.") && void call(true)}>
          Jetzt wiederherstellen
        </button>
      </div>
      {d && !data?.applied && (
        <div className="banner warn"><div>
          <b>Vorschau – noch nichts geändert</b>
          <ul className="plain update-summary">
            <li>Backup vom {data?.created ? new Date(data.created).toLocaleString("de-DE") : "unbekannt"}</li>
            {update && <li><b>{d.changed_cells}</b> Zellen würden sich ändern</li>}
            {addRows && <li><b>{d.added}</b> Zeilen würden ergänzt</li>}
            {removeRows && <li><b>{d.removed}</b> Zeilen würden entfernt</li>}
            <li className="muted">Jetzt {d.rows_now} Zeilen, im Backup {d.rows_backup}</li>
            {d.columns_added.length > 0 && <li>Spalten kämen zurück: {d.columns_added.join(", ")}</li>}
            {d.columns_removed.length > 0 && <li>Spalten würden entfallen: {d.columns_removed.join(", ")}</li>}
          </ul>
          {d.items && d.items.length > 0 && (d.items.length === d.items_total ? (
            <details open={d.items.length <= 30}>
              <summary>Einzelne Zeilen abwählen ({d.items.length - skip.length} von {d.items.length} werden übernommen)</summary>
              <div className="row-buttons">
                <button type="button" onClick={() => setSkip([])}>Alle anhaken</button>
                <button type="button" onClick={() => setSkip(d.items!.map((i) => i.idx))}>Alle abwählen</button>
              </div>
              <div className="column-pick-list">
                {d.items.map((i) => (
                  <label key={i.idx} className="check">
                    <input type="checkbox" checked={!skip.includes(i.idx)}
                      onChange={() => setSkip(skip.includes(i.idx) ? skip.filter((x) => x !== i.idx) : [...skip, i.idx])} />
                    {i.kind === "changed" ? "Ändern" : i.kind === "added" ? "Ergänzen" : "Entfernen"}: {i.label || `Zeile ${i.idx + 1}`}
                    {i.columns.length > 0 && <span className="muted"> ({i.columns.join(", ")})</span>}
                  </label>
                ))}
              </div>
            </details>
          ) : <p className="muted">Zu viele Abweichungen ({d.items_total}) für die Einzelauswahl – es wird alles übernommen.</p>)}
        </div></div>
      )}
      {data?.applied && <div className="banner ok-banner"><div><b>Wiederhergestellt</b> – {(data.result as { rows: number; added?: number; removed?: number } | undefined)?.rows ?? 0} Zeilen geändert{data.result?.added ? `, ${data.result.added} ergänzt` : ""}{data.result?.removed ? `, ${data.result.removed} entfernt` : ""}.</div></div>}
      {error && <p className="error">{error}</p>}
    </fieldset>
  );
}
