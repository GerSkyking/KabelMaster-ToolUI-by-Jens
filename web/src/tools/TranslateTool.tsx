// Übersetzer: Werte aus einer zweiten Tabelle (Liste oder Datei) über eine Schlüsselspalte (z. B. W-Nummer) eintragen.
import { useCallback, useEffect, useMemo, useState } from "react";
import { api, errorText, fetchFile, saveBlob, upload } from "../api";
import { syncDataset } from "../sync";
import { Config, Notice, TemplateBar, useDebounced } from "./common";
import type { ToolProps } from "./types";

interface Sources { project_id: number; datasets: { id: number; name: string }[]; files: string[] }
interface SourceInfo { columns: string[]; total: number; rows: unknown[][] }
interface MappingRow { source: string; target: string; mode: "empty" | "overwrite" }
interface Cell { target: string; old: unknown; new: unknown; changed: boolean }
interface SampleRow { row: number; key: unknown; status: "match" | "none" | "empty_key" | "ambiguous"; cells: Cell[] }
interface Preview {
  stats: Record<string, number>; new_columns: string[]; sample: SampleRow[]; unmatched_keys: string[];
}
interface Settings {
  source: string; // "dataset:<id>" | "file:<name>" | ""
  key_a: string; key_b: string; ignore_case: boolean; ignore_separators: boolean;
  duplicates: "first" | "last" | "skip"; mappings: MappingRow[];
}

const EMPTY: Settings = { source: "", key_a: "", key_b: "", ignore_case: true, ignore_separators: true, duplicates: "first", mappings: [] };
const NEW_COLUMN = "__new__";
const STATUS: Record<SampleRow["status"], string> = {
  match: "Treffer", none: "kein Treffer", empty_key: "Schlüssel leer", ambiguous: "mehrdeutig (übersprungen)",
};
const show = (v: unknown) => (v === null || v === undefined || v === "" ? "–" : String(v));
const norm = (s: string) => s.toLowerCase().replace(/[\s\-_.]+/g, "");

function guessKey(columns: string[]): string {
  return columns.find((c) => /w[\s-]?(nr|nummer)|w-?num/i.test(c)) ?? columns.find((c) => /nummer|\bnr\b/i.test(c)) ?? "";
}

function toRef(source: string) {
  if (source.startsWith("dataset:")) return { kind: "dataset", dataset_id: Number(source.slice(8)) };
  if (source.startsWith("file:")) return { kind: "file", file: source.slice(5) };
  return null;
}

const storageKey = (datasetId: number) => `uwkm:translate:${datasetId}`;

function readSettings(datasetId: number): Settings {
  try {
    const raw = localStorage.getItem(storageKey(datasetId));
    return raw ? { ...EMPTY, ...(JSON.parse(raw) as Partial<Settings>) } : EMPTY;
  } catch {
    return EMPTY;
  }
}

export function TranslateTool({ backend, datasetId, columns }: ToolProps) {
  const [cfg, setCfg] = useState<Settings>(() => readSettings(datasetId));
  const [sources, setSources] = useState<Sources | null>(null);
  const [info, setInfo] = useState<SourceInfo | null>(null);
  const [preview, setPreview] = useState<Preview | null>(null);
  const [filter, setFilter] = useState<"changes" | "none" | "all">("changes");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");
  const [progress, setProgress] = useState<number | null>(null);

  const set = (change: Partial<Settings>) => setCfg((c) => ({ ...c, ...change }));
  useEffect(() => {
    try {
      localStorage.setItem(storageKey(datasetId), JSON.stringify(cfg));
    } catch {
      /* Speicher nicht verfügbar - Einstellung gilt nur für diese Sitzung */
    }
  }, [cfg, datasetId]);

  const loadSources = useCallback(async () => {
    try {
      setSources(await api<Sources>(`/api/datasets/${datasetId}/translate/sources`));
    } catch (e) {
      setError(errorText(e));
    }
  }, [datasetId]);
  useEffect(() => {
    void syncDataset(backend).catch(() => undefined); // lokale Änderungen zuerst zum Server
    void loadSources();
  }, [backend, loadSources]);

  // Quelle gewählt: Spalten und erste Zeilen holen, Schlüssel vorschlagen
  useEffect(() => {
    const ref = toRef(cfg.source);
    setInfo(null);
    if (!ref) return;
    let alive = true;
    api<SourceInfo>(`/api/datasets/${datasetId}/translate/source`, { method: "POST", body: ref })
      .then((data) => {
        if (!alive) return;
        setInfo(data);
        setError("");
        setCfg((c) => {
          const keyA = columns.includes(c.key_a) ? c.key_a : guessKey(columns);
          const keyB = data.columns.includes(c.key_b) ? c.key_b
            : data.columns.find((n) => keyA && norm(n) === norm(keyA)) ?? guessKey(data.columns);
          return { ...c, key_a: keyA, key_b: keyB,
            mappings: c.mappings.filter((m) => data.columns.includes(m.source)) };
        });
      })
      .catch((e) => alive && setError(errorText(e)));
    return () => { alive = false; };
  }, [cfg.source, datasetId, columns.join("\u0001")]); // eslint-disable-line react-hooks/exhaustive-deps

  const ready = !!toRef(cfg.source) && !!cfg.key_a && !!cfg.key_b
    && cfg.mappings.length > 0 && cfg.mappings.every((m) => m.source && m.target.trim());
  const body = useMemo(() => ({
    source: toRef(cfg.source), key_a: cfg.key_a, key_b: cfg.key_b, ignore_case: cfg.ignore_case,
    ignore_separators: cfg.ignore_separators, duplicates: cfg.duplicates, mappings: cfg.mappings,
  }), [cfg]);

  const runPreview = useCallback(async () => {
    if (!ready) {
      setPreview(null);
      return;
    }
    setBusy(true);
    try {
      setPreview(await api<Preview>(`/api/datasets/${datasetId}/translate/preview`, { method: "POST", body }));
      setError("");
    } catch (e) {
      setPreview(null);
      setError(errorText(e));
    } finally {
      setBusy(false);
    }
  }, [ready, body, datasetId]);
  useDebounced(() => void runPreview(), [JSON.stringify(body), ready]);

  const apply = async () => {
    if (!preview) return;
    const s = preview.stats;
    if (!s.changed_cells) {
      setMessage("Es gibt nichts zu ändern.");
      return;
    }
    const extra = preview.new_columns.length ? `\nNeue Spalte(n): ${preview.new_columns.join(", ")}` : "";
    if (!confirm(`${s.changed_cells} Zelle(n) in ${s.changed_rows} Zeile(n) der Liste ändern?${extra}\n\nAlle anderen Spalten bleiben unverändert.`)) return;
    setBusy(true);
    setMessage("");
    try {
      await syncDataset(backend).catch(() => undefined);
      const done = await api<{ changed_rows: number; changed_cells: number }>(
        `/api/datasets/${datasetId}/translate/apply`, { method: "POST", body });
      await syncDataset(backend).catch(() => undefined);
      setMessage(`${done.changed_cells} Zelle(n) in ${done.changed_rows} Zeile(n) eingetragen.`);
      await runPreview();
    } catch (e) {
      setError(errorText(e));
    } finally {
      setBusy(false);
    }
  };

  const exportExcel = async () => {
    setBusy(true);
    try {
      saveBlob(await fetchFile(`/api/datasets/${datasetId}/translate/export`, body, "uebersetzt.xlsx"));
    } catch (e) {
      setError(errorText(e));
    } finally {
      setBusy(false);
    }
  };

  const uploadSource = async (file: File | undefined) => {
    if (!file || !sources) return;
    setError("");
    setProgress(0);
    const form = new FormData();
    form.append("file", file);
    try {
      const saved = await upload<{ name: string }>(`/api/projects/${sources.project_id}/files`, form,
        (loaded, total) => setProgress(Math.round((loaded / total) * 100)));
      await loadSources();
      set({ source: `file:${saved.name}` });
    } catch (e) {
      setError(errorText(e));
    } finally {
      setProgress(null);
    }
  };

  const setMapping = (index: number, change: Partial<MappingRow>) =>
    set({ mappings: cfg.mappings.map((m, i) => (i === index ? { ...m, ...change } : m)) });
  const addMapping = () => set({ mappings: [...cfg.mappings, { source: "", target: "", mode: "overwrite" }] });
  const mapSameNames = () => {
    if (!info) return;
    const taken = new Set(cfg.mappings.map((m) => m.target));
    const extra = info.columns
      .filter((c) => c !== cfg.key_b && columns.includes(c) && c !== cfg.key_a && !taken.has(c))
      .map((c): MappingRow => ({ source: c, target: c, mode: "overwrite" }));
    set({ mappings: [...cfg.mappings, ...extra] });
  };

  const applyTemplate = (data: Config) =>
    setCfg({ ...EMPTY, ...Object.fromEntries(Object.keys(EMPTY).filter((k) => k in data).map((k) => [k, data[k]])) } as Settings);

  const targets = columns.filter((c) => c !== cfg.key_a);
  const newName = (source: string) => (!source ? "Neue Spalte" : columns.includes(source) ? `${source} (neu)` : source);
  const rows = (preview?.sample ?? []).filter((r) =>
    filter === "all" ? true : filter === "none" ? r.status !== "match" : r.cells.some((c) => c.changed));
  const s = preview?.stats;

  return (
    <div className="tool">
      <Notice error={error} />
      <TemplateBar tabId="translate" config={cfg} columns={columns} onApply={applyTemplate} />

      <section className="card">
        <h3>1. Quelle (zweite Tabelle)</h3>
        <div className="inline-form">
          <label>Liste oder Datei
            <select value={cfg.source} onChange={(e) => set({ source: e.target.value, key_b: "" })}>
              <option value="">– wählen –</option>
              {!!sources?.datasets.length && <optgroup label="Listen dieses Projekts">
                {sources.datasets.map((d) => <option key={d.id} value={`dataset:${d.id}`}>{d.name}</option>)}
              </optgroup>}
              {!!sources?.files.length && <optgroup label="Dateien im Arbeitsverzeichnis">
                {sources.files.map((f) => <option key={f} value={`file:${f}`}>{f}</option>)}
              </optgroup>}
            </select>
          </label>
          <label className="upload-inline">Datei hochladen (.xlsx, .xls, .csv)
            <input type="file" accept=".xlsx,.xls,.csv" disabled={progress !== null}
              onChange={(e) => { void uploadSource(e.target.files?.[0]); e.target.value = ""; }} />
          </label>
          {progress !== null && <span><progress max={100} value={progress} /> {progress} %</span>}
        </div>
        {info && (
          <details open>
            <summary>Vorschau der Quelle – {info.total} Zeile(n), erste {info.rows.length}</summary>
            <div className="table-wrap">
              <table>
                <thead><tr>{info.columns.map((c) => <th key={c} className={c === cfg.key_b ? "keycol" : ""}>{c}</th>)}</tr></thead>
                <tbody>{info.rows.map((r, i) => (
                  <tr key={i}>{r.map((v, j) => <td key={j} className={info.columns[j] === cfg.key_b ? "keycol" : ""}>{show(v)}</td>)}</tr>
                ))}</tbody>
              </table>
            </div>
          </details>
        )}
      </section>

      <section className="card">
        <h3>2. Schlüssel (womit Zeilen zusammengehören)</h3>
        <div className="fields">
          <label>Spalte in dieser Liste
            <select value={cfg.key_a} onChange={(e) => set({ key_a: e.target.value })}>
              <option value="">– wählen –</option>{columns.map((c) => <option key={c}>{c}</option>)}
            </select>
          </label>
          <label>Spalte in der Quelle
            <select value={cfg.key_b} disabled={!info} onChange={(e) => set({ key_b: e.target.value })}>
              <option value="">– wählen –</option>{info?.columns.map((c) => <option key={c}>{c}</option>)}
            </select>
          </label>
          <label>Mehrfach in der Quelle
            <select value={cfg.duplicates} onChange={(e) => set({ duplicates: e.target.value as Settings["duplicates"] })}>
              <option value="first">ersten Treffer nehmen</option><option value="last">letzten Treffer nehmen</option>
              <option value="skip">überspringen</option>
            </select>
          </label>
          <label className="check"><input type="checkbox" checked={cfg.ignore_case} onChange={(e) => set({ ignore_case: e.target.checked })} />Groß-/Kleinschreibung ignorieren</label>
          <label className="check"><input type="checkbox" checked={cfg.ignore_separators} onChange={(e) => set({ ignore_separators: e.target.checked })} />Leerzeichen, „-“, „_“, „.“, „/“ ignorieren (W-001 = W001)</label>
        </div>
      </section>

      <section className="card">
        <h3>3. Was wohin geschrieben wird</h3>
        <p className="muted">Nur die hier zugeordneten Spalten werden verändert. Alle anderen Spalten der Liste bleiben unberührt.</p>
        <table>
          <thead><tr><th>Spalte der Quelle</th><th></th><th>Spalte in dieser Liste</th><th>Wenn dort schon etwas steht</th><th></th></tr></thead>
          <tbody>
            {cfg.mappings.map((m, i) => {
              const isNew = m.target !== "" && !targets.includes(m.target);
              return (
                <tr key={i}>
                  <td>
                    <select value={m.source} onChange={(e) => setMapping(i, { source: e.target.value })}>
                      <option value="">– wählen –</option>{info?.columns.filter((c) => c !== cfg.key_b).map((c) => <option key={c}>{c}</option>)}
                    </select>
                  </td>
                  <td>→</td>
                  <td>
                    <span className="inline">
                      <select value={isNew ? NEW_COLUMN : m.target} onChange={(e) => setMapping(i, { target: e.target.value === NEW_COLUMN ? newName(m.source) : e.target.value })}>
                        <option value="">– wählen –</option>
                        {targets.map((c) => <option key={c}>{c}</option>)}
                        <option value={NEW_COLUMN}>+ Neue Spalte …</option>
                      </select>
                      {isNew && <input placeholder="Name der neuen Spalte" value={m.target} onChange={(e) => setMapping(i, { target: e.target.value })} />}
                    </span>
                  </td>
                  <td>
                    <select value={m.mode} onChange={(e) => setMapping(i, { mode: e.target.value as MappingRow["mode"] })}>
                      <option value="overwrite">überschreiben</option><option value="empty">nur leere Zellen füllen</option>
                    </select>
                  </td>
                  <td><button className="link" onClick={() => set({ mappings: cfg.mappings.filter((_, j) => j !== i) })}>✕</button></td>
                </tr>
              );
            })}
          </tbody>
        </table>
        <div className="inline">
          <button onClick={addMapping} disabled={!info}>Zuordnung hinzufügen</button>
          <button onClick={mapSameNames} disabled={!info} title="Spalten der Quelle, die in der Liste gleich heißen">Gleichnamige Spalten zuordnen</button>
        </div>
      </section>

      <section className="card">
        <h3>4. Ergebnis {busy && <span className="muted">· rechnet …</span>}</h3>
        {!ready && <p className="muted">Quelle, beide Schlüsselspalten und mindestens eine Zuordnung wählen.</p>}
        {s && (
          <>
            <p className="inline">
              <span className="chip">{s.rows} Zeilen in der Liste</span>
              <span className="chip">{s.matched} Treffer</span>
              <span className={`chip${s.unmatched ? " warn" : ""}`}>{s.unmatched} ohne Treffer</span>
              {s.empty_key > 0 && <span className="chip">{s.empty_key} ohne Schlüssel</span>}
              {s.ambiguous > 0 && <span className="chip warn">{s.ambiguous} mehrdeutig</span>}
              {s.duplicate_keys > 0 && <span className="chip">{s.duplicate_keys} Schlüssel mehrfach in der Quelle</span>}
              <b>{s.changed_cells} Zelle(n) in {s.changed_rows} Zeile(n) würden geändert</b>
            </p>
            {!!preview?.new_columns.length && <p>Neue Spalte(n): <b>{preview.new_columns.join(", ")}</b></p>}
            <div className="inline-form">
              <label>Anzeigen
                <select value={filter} onChange={(e) => setFilter(e.target.value as typeof filter)}>
                  <option value="changes">nur Änderungen</option><option value="none">ohne Treffer</option><option value="all">alle</option>
                </select>
              </label>
              <button className="primary" disabled={busy || !s.changed_cells} onClick={() => void apply()}>Auf die Liste anwenden</button>
              <button disabled={busy} onClick={() => void exportExcel()} title="Die gespeicherte Liste bleibt unverändert">Als Excel herunterladen</button>
            </div>
            {message && <p className="ok">{message}</p>}
            <div className="table-wrap tall">
              <table>
                <thead>
                  <tr><th>Zeile</th><th>Schlüssel</th><th>Status</th>
                    {cfg.mappings.map((m, i) => <th key={i}>{m.target || "?"}</th>)}</tr>
                </thead>
                <tbody>
                  {rows.map((r) => (
                    <tr key={r.row}>
                      <td>{r.row}</td><td>{show(r.key)}</td><td className={r.status === "match" ? "" : "warn"}>{STATUS[r.status]}</td>
                      {r.cells.map((c, i) => (
                        <td key={i} className={c.changed ? "changed" : ""}>
                          {c.changed ? <><s className="muted">{show(c.old)}</s> → <b>{show(c.new)}</b></> : show(c.old)}
                        </td>
                      ))}
                    </tr>
                  ))}
                  {!rows.length && <tr><td className="muted" colSpan={3 + cfg.mappings.length}>Keine Zeilen für diese Ansicht.</td></tr>}
                </tbody>
              </table>
            </div>
            {!!preview?.unmatched_keys.length && (
              <details>
                <summary>Schlüssel der Liste ohne Treffer in der Quelle ({s.unmatched})</summary>
                <p>{preview.unmatched_keys.join(", ")}{s.unmatched > preview.unmatched_keys.length ? " …" : ""}</p>
              </details>
            )}
          </>
        )}
      </section>
    </div>
  );
}
