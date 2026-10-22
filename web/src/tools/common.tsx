// Gemeinsame Bausteine der Werkzeug-Reiter (Konfiguration, Vorlagen, Tabellenvorschau, Export).
import { ReactNode, useCallback, useEffect, useMemo, useRef, useState } from "react";
import { ApiError, OfflineError, api, errorText, fetchFile, saveBlob } from "../api";
import { Backend, syncDataset } from "../sync";

/* eslint-disable @typescript-eslint/no-explicit-any */
export type Config = Record<string, any>;

export interface ColumnCfg {
  name: string;
  search_enabled: boolean;
  output_enabled: boolean;
  output_order: number;
  width_px: number;
}

export const DISPLAY_DEFAULTS = {
  font_size: 10, alternate_row_colors: false, landscape: false, row_height_px: 20, header_font_size: 10,
  header_row_height_px: 20, word_wrap: true, min_font_size: 5,
};

export const TOOL_OF_TAB: Record<string, string> = {
  single_search: "search", batch_search: "batch", highlight: "highlight", kmk: "kmk", cabinet: "cabinet",
};

function defaults(columns: string[]): Config {
  return {
    columns: columns.map((name, i) => ({ name, search_enabled: true, output_enabled: true, output_order: i, width_px: 120 })),
    sort: { column: null, ascending: true },
    separator: { enabled: false, column: null, height_px: 10 },
    display: { ...DISPLAY_DEFAULTS },
    batch_search_terms: [],
    batch: { result_column_enabled: false, result_column_name: "Ergebnis", separator: "*" },
    colors: [
      { id: 1, name: "Gelb", color_hex: "#FFFF00", alpha: 30, column_id: null },
      { id: 2, name: "Rot", color_hex: "#FF0000", alpha: 50, column_id: null },
      { id: 3, name: "Grün", color_hex: "#00FF00", alpha: 20, column_id: null },
    ],
    color_columns: [],
    color_search_terms: [],
    color_min_matches: 2,
    kmk_config: {
      kmk_type: { name: "KMK-2", height_mm: 8, width_mm: 29 }, font_size_pt: 6, frame_enabled: true, frame_width_pt: 0.5,
      frame_color: "#000000", frame_padding_pt: 2, header_mode: "first_field", seamless: true, include_reste: true,
      auto_shrink: true, min_font_size_pt: 3, label_content: {},
    },
    cabinet_config: {
      formats: [
        { pattern: "+XX", enabled: true, with_field: false }, { pattern: "xx+XX", enabled: false, with_field: true },
        { pattern: "xx-XX", enabled: false, with_field: true }, { pattern: "-XX", enabled: false, with_field: false },
      ],
      cabinet_column: true, fields: { E: false, J: false, H: false }, custom_fields: "",
    },
  };
}

/** Fügt neue Dataset-Spalten hinzu und entfernt verschwundene, ohne die übrige Konfiguration anzufassen. */
export function reconcile(config: Config, columns: string[]): Config {
  const known = new Map<string, ColumnCfg>((config.columns ?? []).map((c: ColumnCfg) => [c.name, c]));
  let order = Math.max(-1, ...[...known.values()].map((c) => c.output_order)) + 1;
  const merged = columns.map((name) => known.get(name) ?? { name, search_enabled: true, output_enabled: true, output_order: order++, width_px: 120 });
  return { ...config, columns: merged };
}

const storageKey = (datasetId: number, tab: string) => `uwkm:cfg:${datasetId}:${tab}`;

function readStorage<T>(key: string): T | null {
  try {
    const raw = localStorage.getItem(key);
    return raw ? (JSON.parse(raw) as T) : null;
  } catch {
    return null;
  }
}
function writeStorage(key: string, value: unknown): void {
  try {
    localStorage.setItem(key, JSON.stringify(value));
  } catch {
    /* Speicher nicht verfügbar - die Einstellung gilt dann nur für diese Sitzung */
  }
}

export function useToolConfig(datasetId: number, tab: string, columns: string[]) {
  const [config, setConfig] = useState<Config>(() => reconcile({ ...defaults(columns), ...(readStorage<Config>(storageKey(datasetId, tab)) ?? {}) }, columns));
  const columnsKey = columns.join("\u0001");
  useEffect(() => setConfig((c) => reconcile(c, columns)), [columnsKey]); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => writeStorage(storageKey(datasetId, tab), config), [config, datasetId, tab]);
  const update = useCallback((partial: Config) => setConfig((c) => ({ ...c, ...partial })), []);
  const replace = useCallback((next: Config) => setConfig(reconcile({ ...defaults(columns), ...next }, columns)), [columns]);
  return { config, update, replace };
}

// ---- Globale Felder (Datum, Ersteller, ...) ----

export interface GlobalField { value: string; enabled: boolean }
export type Globals = Record<"date" | "creator" | "company" | "project" | "location", GlobalField>;
const GLOBAL_KEY = "uwkm:globals";

export function useGlobals(creator: string) {
  const [globals, setGlobals] = useState<Globals>(() => {
    const saved = readStorage<Globals>(GLOBAL_KEY);
    const base: Globals = {
      date: { value: new Date().toISOString().slice(0, 10), enabled: true },
      creator: { value: creator, enabled: true }, company: { value: "", enabled: true },
      project: { value: "", enabled: true }, location: { value: "", enabled: true },
    };
    return saved ? { ...base, ...saved, date: { value: new Date().toISOString().slice(0, 10), enabled: saved.date?.enabled ?? true } } : base;
  });
  useEffect(() => writeStorage(GLOBAL_KEY, globals), [globals]);
  return [globals, setGlobals] as const;
}

const GLOBAL_LABELS: Record<keyof Globals, string> = {
  date: "Datum", creator: "Ersteller", company: "Firma", project: "Projekt / Funktion", location: "Ort",
};

export function GlobalFieldsPanel({ globals, onChange }: { globals: Globals; onChange: (g: Globals) => void }) {
  return (
    <details className="card">
      <summary>Kopfzeile und Dateiname (Datum, Ersteller, Firma …)</summary>
      <div className="fields">
        {(Object.keys(GLOBAL_LABELS) as (keyof Globals)[]).map((key) => (
          <label key={key}>
            {GLOBAL_LABELS[key]}
            <span className="inline">
              <input value={globals[key].value} onChange={(e) => onChange({ ...globals, [key]: { ...globals[key], value: e.target.value } })} />
              <input type="checkbox" title="in Export übernehmen" checked={globals[key].enabled}
                onChange={(e) => onChange({ ...globals, [key]: { ...globals[key], enabled: e.target.checked } })} />
            </span>
          </label>
        ))}
      </div>
    </details>
  );
}

// ---- Spalten und Ausgabe ----

export function ColumnPanel({ config, update, search = true }: { config: Config; update: (c: Config) => void; search?: boolean }) {
  const cols: ColumnCfg[] = config.columns;
  const set = (name: string, change: Partial<ColumnCfg>) =>
    update({ columns: cols.map((c) => (c.name === name ? { ...c, ...change } : c)) });
  const ordered = [...cols].sort((a, b) => a.output_order - b.output_order);
  const move = (name: string, dir: -1 | 1) => {
    const list = ordered.map((c) => c.name);
    const i = list.indexOf(name);
    const j = i + dir;
    if (j < 0 || j >= list.length) return;
    [list[i], list[j]] = [list[j], list[i]];
    update({ columns: cols.map((c) => ({ ...c, output_order: list.indexOf(c.name) })) });
  };
  const all = (field: "search_enabled" | "output_enabled", value: boolean) => update({ columns: cols.map((c) => ({ ...c, [field]: value })) });
  return (
    <details className="card" open>
      <summary>Spalten</summary>
      <div className="table-wrap tall">
        <table>
          <thead>
            <tr>
              <th>Spalte</th>
              {search && <th>Suche <button className="link" onClick={() => all("search_enabled", true)}>alle</button> <button className="link" onClick={() => all("search_enabled", false)}>keine</button></th>}
              <th>Ausgabe <button className="link" onClick={() => all("output_enabled", true)}>alle</button> <button className="link" onClick={() => all("output_enabled", false)}>keine</button></th>
              <th>Reihenfolge</th>
            </tr>
          </thead>
          <tbody>
            {ordered.map((c) => (
              <tr key={c.name}>
                <td>{c.name}</td>
                {search && <td><input type="checkbox" checked={c.search_enabled} onChange={(e) => set(c.name, { search_enabled: e.target.checked })} /></td>}
                <td><input type="checkbox" checked={c.output_enabled} onChange={(e) => set(c.name, { output_enabled: e.target.checked })} /></td>
                <td><button onClick={() => move(c.name, -1)}>↑</button> <button onClick={() => move(c.name, 1)}>↓</button></td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </details>
  );
}

export function OutputPanel({ config, update }: { config: Config; update: (c: Config) => void }) {
  const names: string[] = config.columns.map((c: ColumnCfg) => c.name);
  const sort = config.sort, sep = config.separator, d = config.display;
  const setDisplay = (change: Config) => update({ display: { ...d, ...change } });
  return (
    <details className="card">
      <summary>Sortierung, Trennzeilen und Darstellung</summary>
      <div className="fields">
        <label>Sortieren nach
          <span className="inline">
            <select value={sort.column ?? ""} onChange={(e) => update({ sort: { ...sort, column: e.target.value || null } })}>
              <option value="">– keine –</option>{names.map((n) => <option key={n}>{n}</option>)}
            </select>
            <select value={sort.ascending ? "asc" : "desc"} onChange={(e) => update({ sort: { ...sort, ascending: e.target.value === "asc" } })}>
              <option value="asc">aufsteigend</option><option value="desc">absteigend</option>
            </select>
          </span>
        </label>
        <label>Trennzeile bei Wechsel in
          <span className="inline">
            <input type="checkbox" checked={sep.enabled} onChange={(e) => update({ separator: { ...sep, enabled: e.target.checked } })} />
            <select value={sep.column ?? ""} onChange={(e) => update({ separator: { ...sep, column: e.target.value || null } })}>
              <option value="">– Spalte –</option>{names.map((n) => <option key={n}>{n}</option>)}
            </select>
          </span>
        </label>
        <label>Schriftgröße<input type="number" min={4} max={30} value={d.font_size} onChange={(e) => setDisplay({ font_size: Number(e.target.value) })} /></label>
        <label className="check"><input type="checkbox" checked={d.landscape} onChange={(e) => setDisplay({ landscape: e.target.checked })} />Querformat</label>
        <label className="check"><input type="checkbox" checked={d.alternate_row_colors} onChange={(e) => setDisplay({ alternate_row_colors: e.target.checked })} />Zeilen abwechselnd färben</label>
        <label className="check"><input type="checkbox" checked={d.word_wrap} onChange={(e) => setDisplay({ word_wrap: e.target.checked })} />Zeilenumbruch</label>
      </div>
    </details>
  );
}

// ---- Vorlagen (global: Vorlagen/<Benutzer>/<Name>) ----

interface TemplateInfo { id: number; name: string; owner: string; path: string; editable: boolean; tab_id: string }

export function TemplateBar({ tabId, config, columns, onApply }: { tabId: string; config: Config; columns: string[]; onApply: (data: Config) => void }) {
  const [list, setList] = useState<TemplateInfo[]>([]);
  const [selected, setSelected] = useState("");
  const [name, setName] = useState("");
  const [message, setMessage] = useState("");
  const load = useCallback(async () => {
    try {
      setList(await api<TemplateInfo[]>(`/api/templates?tab_id=${tabId}`));
    } catch (e) {
      setMessage(errorText(e));
    }
  }, [tabId]);
  useEffect(() => void load(), [load]);
  const current = list.find((t) => String(t.id) === selected);
  const payload = (templateName: string) => ({ ...config, name: templateName, tab_id: tabId, column_names: columns });

  const run = async (action: () => Promise<void>, ok: string) => {
    setMessage("");
    try {
      await action();
      setMessage(ok);
      await load();
    } catch (e) {
      setMessage(errorText(e));
    }
  };
  const apply = () => run(async () => onApply((await api<{ data: Config }>(`/api/templates/${selected}`)).data), `Vorlage „${current?.name}“ angewendet.`);
  const saveNew = () => run(async () => {
    const t = await api<TemplateInfo>("/api/templates", { method: "POST", body: { name, tab_id: tabId, data: payload(name) } });
    setSelected(String(t.id));
  }, `Gespeichert unter Vorlagen/…/${name}.`);
  const overwrite = () => run(async () => {
    await api(`/api/templates/${selected}`, { method: "PUT", body: { name: current!.name, tab_id: tabId, data: payload(current!.name) } });
  }, "Vorlage aktualisiert.");
  const remove = () => run(async () => {
    await api(`/api/templates/${selected}`, { method: "DELETE" });
    setSelected("");
  }, "Vorlage gelöscht.");
  const exportJson = () => {
    const blob = new Blob([JSON.stringify(payload(current?.name ?? "Vorlage"), null, 2)], { type: "application/json" });
    saveBlob({ blob, filename: `${current?.name ?? "Vorlage"}.json` });
  };
  const importJson = (file: File | undefined) => {
    if (!file) return;
    void run(async () => {
      const data = JSON.parse(await file.text());
      onApply(data);
      setName(String(data.name ?? file.name.replace(/\.json$/i, "")));
    }, "Vorlage geladen (noch nicht gespeichert).");
  };

  return (
    <section className="card templates">
      <div className="inline-form">
        <label>Vorlage
          <select value={selected} onChange={(e) => setSelected(e.target.value)}>
            <option value="">– wählen –</option>
            {list.map((t) => <option key={t.id} value={t.id}>{t.path}</option>)}
          </select>
        </label>
        <button disabled={!selected} onClick={() => void apply()}>Anwenden</button>
        <button disabled={!current?.editable} onClick={() => void overwrite()} title="Nur Besitzer oder Admin">Überschreiben</button>
        <button className="danger" disabled={!current?.editable} onClick={() => void remove()}>Löschen</button>
        <input placeholder="Neuer Name" value={name} onChange={(e) => setName(e.target.value)} />
        <button disabled={!name.trim()} onClick={() => void saveNew()}>Als neue Vorlage speichern</button>
        <button onClick={exportJson}>JSON-Export</button>
        <label className="upload-inline">JSON-Import<input type="file" accept=".json" onChange={(e) => { importJson(e.target.files?.[0]); e.target.value = ""; }} /></label>
      </div>
      {message && <p className="muted">{message}</p>}
    </section>
  );
}

// ---- Vorschau-Tabelle ----

export interface TablePayload {
  columns: { name: string; width: number }[];
  rows: { values: string[]; separator: boolean; color: string | null; cells: (string | null)[] }[];
  total: number;
  truncated: boolean;
  header: { left: string[]; center: string[]; right: string[] };
}

export function ResultTable({ table }: { table: TablePayload | null }) {
  if (!table) return <p className="muted">Keine Vorschau.</p>;
  const head = [table.header.left.join(" · "), table.header.center.join(" · "), table.header.right.join(" · ")];
  return (
    <div>
      <p className="muted preview-head">{head.filter(Boolean).join("  |  ")} — {table.total} Zeile(n){table.truncated ? " (Vorschau gekürzt)" : ""}</p>
      <div className="table-wrap tall">
        <table>
          <thead><tr>{table.columns.map((c, i) => <th key={i}>{c.name}</th>)}</tr></thead>
          <tbody>
            {table.rows.map((r, i) => (
              <tr key={i} className={r.separator ? "sep-row" : ""} style={r.color ? { background: r.color } : undefined}>
                {r.values.map((v, j) => <td key={j} style={r.cells[j] ? { background: r.cells[j]! } : undefined}>{v}</td>)}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

// ---- Server-Aufrufe (vorher lokale Änderungen übertragen) ----

export function useToolApi(backend: Backend, datasetId: number, tool: string) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const flush = useCallback(async () => {
    try {
      await syncDataset(backend);
    } catch (e) {
      if (e instanceof OfflineError) throw new Error("Die Werkzeuge brauchen eine Verbindung zum Server.");
      if (!(e instanceof ApiError)) throw e;
      throw e;
    }
  }, [backend]);

  const preview = useCallback(async <T,>(body: object): Promise<T | null> => {
    setBusy(true);
    setError("");
    try {
      await flush();
      return await api<T>(`/api/datasets/${datasetId}/tools/${tool}/preview`, { method: "POST", body });
    } catch (e) {
      setError(errorText(e));
      return null;
    } finally {
      setBusy(false);
    }
  }, [datasetId, tool, flush]);

  const exportFile = useCallback(async (body: object, fallback: string) => {
    setBusy(true);
    setError("");
    try {
      await flush();
      const file = await fetchFile(`/api/datasets/${datasetId}/tools/${tool}/export`, body, fallback);
      saveBlob(file);
      return file;
    } catch (e) {
      setError(errorText(e));
      return null;
    } finally {
      setBusy(false);
    }
  }, [datasetId, tool, flush]);

  return { busy, error, setError, preview, exportFile };
}

/** Führt `run` verzögert aus, sobald sich `deps` ändern (Live-Vorschau). */
export function useDebounced(run: () => void, deps: unknown[], delay = 500) {
  const fn = useRef(run);
  fn.current = run;
  useEffect(() => {
    const t = window.setTimeout(() => fn.current(), delay);
    return () => window.clearTimeout(t);
  }, deps); // eslint-disable-line react-hooks/exhaustive-deps
}

export function FormatChoice({ formats, onChange }: { formats: string[]; onChange: (f: string[]) => void }) {
  const toggle = (f: string) => onChange(formats.includes(f) ? formats.filter((x) => x !== f) : [...formats, f]);
  return (
    <span className="inline">
      <label className="check"><input type="checkbox" checked={formats.includes("xlsx")} onChange={() => toggle("xlsx")} />Excel</label>
      <label className="check"><input type="checkbox" checked={formats.includes("pdf")} onChange={() => toggle("pdf")} />PDF</label>
    </span>
  );
}

export function Notice({ error, children }: { error?: string; children?: ReactNode }) {
  return <>{error && <div className="banner error">{error}</div>}{children}</>;
}

/** Suchbegriffe als Liste mit Aktiv-Haken; Mehrfach-Einfügen (eine Zeile pro Begriff) möglich. */
export function TermList({ terms, onChange, onPick, picked, counts }: {
  terms: { term: string; enabled: boolean }[]; onChange: (t: { term: string; enabled: boolean }[]) => void;
  onPick?: (term: string) => void; picked?: string; counts?: Record<string, number>;
}) {
  const [text, setText] = useState("");
  const add = () => {
    const incoming = text.split(/\r?\n/).map((t) => t.trim()).filter(Boolean);
    if (!incoming.length) return;
    const have = new Set(terms.map((t) => t.term));
    onChange([...terms, ...incoming.filter((t) => !have.has(t)).map((term) => ({ term, enabled: true }))]);
    setText("");
  };
  return (
    <div>
      <div className="inline-form">
        <textarea rows={2} placeholder="Suchbegriffe (eine Zeile pro Begriff)" value={text} onChange={(e) => setText(e.target.value)} />
        <button onClick={add} disabled={!text.trim()}>Hinzufügen</button>
        <button onClick={() => onChange([])} disabled={!terms.length}>Alle entfernen</button>
      </div>
      <ul className="plain terms">
        {terms.map((t, i) => (
          <li key={t.term} className={picked === t.term ? "picked" : ""}>
            <input type="checkbox" checked={t.enabled} onChange={(e) => onChange(terms.map((x, j) => (j === i ? { ...x, enabled: e.target.checked } : x)))} />
            <button className="link" onClick={() => onPick?.(t.term)}>{t.term}</button>
            {counts && <span className="chip">{counts[t.term] ?? 0} Treffer</span>}
            <button className="link" onClick={() => onChange(terms.filter((_, j) => j !== i))}>✕</button>
          </li>
        ))}
      </ul>
    </div>
  );
}

export const requestBody = (config: Config, globals: Globals, extra: object = {}) => ({ config, globals, ...extra });

export function useRequestKey(...parts: unknown[]): string {
  return useMemo(() => JSON.stringify(parts), [JSON.stringify(parts)]); // eslint-disable-line react-hooks/exhaustive-deps
}
