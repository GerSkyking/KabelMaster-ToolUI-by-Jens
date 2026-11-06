import { useEffect, useMemo, useState } from "react";
import { errorText, saveBlob, upload } from "../api";

interface SheetInfo { name: string; columns: { name: string; letter: string }[] }

/** Eine hochgeladene Excel-Datei samt Blattwahl und Kopfzeile; die Spalten kommen vom Server. */
function useWorkbook() {
  const [file, setFile] = useState<File | null>(null);
  const [sheets, setSheets] = useState<SheetInfo[]>([]);
  const [sheet, setSheet] = useState("");
  const [header, setHeader] = useState(1);
  const [error, setError] = useState("");

  useEffect(() => {
    if (!file) { setSheets([]); setSheet(""); return; }
    let stale = false;
    const form = new FormData();
    form.append("file", file);
    form.append("header_row", String(header));
    setError("");
    upload<{ sheets: SheetInfo[] }>("/api/exceltools/inspect", form)
      .then((r) => {
        if (stale) return;
        setSheets(r.sheets);
        setSheet((cur) => (r.sheets.some((s) => s.name === cur) ? cur : r.sheets[0]?.name ?? ""));
      })
      .catch((e) => { if (!stale) { setSheets([]); setError(errorText(e)); } });
    return () => { stale = true; };
  }, [file, header]);

  const columns = sheets.find((s) => s.name === sheet)?.columns.map((c) => c.name) ?? [];
  return { file, setFile, sheets, sheet, setSheet, header, setHeader, error, columns };
}
type Workbook = ReturnType<typeof useWorkbook>;

function FileBox({ title, wb, hint, allSheets }: { title: string; wb: Workbook; hint?: string; allSheets?: boolean }) {
  return (
    <fieldset className="card settings">
      <legend>{title}</legend>
      <div className="grid2">
        <label>Excel-Datei (.xlsx)
          <input type="file" accept=".xlsx" onChange={(e) => wb.setFile(e.target.files?.[0] ?? null)} />
        </label>
        {wb.sheets.length > 0 && !allSheets && (
          <label>Blatt
            <select value={wb.sheet} onChange={(e) => wb.setSheet(e.target.value)}>
              {wb.sheets.map((s) => <option key={s.name} value={s.name}>{s.name}</option>)}
            </select>
          </label>
        )}
        {wb.file && (
          <label>Zeile mit den Spaltenüberschriften
            <input type="number" min={1} max={1000} value={wb.header} onChange={(e) => wb.setHeader(Math.max(1, Number(e.target.value) || 1))} />
          </label>
        )}
      </div>
      {allSheets && wb.sheets.length > 0 && <p className="muted">{wb.sheets.length} Blätter: {wb.sheets.map((s) => s.name).join(", ")}</p>}
      {hint && <p className="muted">{hint}</p>}
      {wb.error && <p className="error">{wb.error}</p>}
    </fieldset>
  );
}

function pickKey(columns: string[]): string {
  return columns.find((c) => /kabel/i.test(c)) ?? columns[0] ?? "";
}

function Select({ label, value, onChange, options, empty }: { label: string; value: string; onChange: (v: string) => void; options: string[]; empty?: string }) {
  return (
    <label>{label}
      <select value={value} onChange={(e) => onChange(e.target.value)}>
        {empty !== undefined && <option value="">{empty}</option>}
        {options.map((c) => <option key={c} value={c}>{c}</option>)}
      </select>
    </label>
  );
}

function List({ title, items, total }: { title: string; items: string[]; total: number }) {
  if (!total) return null;
  return (
    <details>
      <summary>{title}: <b>{total}</b></summary>
      <p className="muted">{items.join(", ")}{total > items.length ? ` … (+${total - items.length})` : ""}</p>
    </details>
  );
}

interface Change { sheet?: string; row: number; key: string; column: string; old: unknown; new: unknown }
function Changes({ changes, total }: { changes: Change[]; total: number }) {
  if (!changes.length) return null;
  const show = (v: unknown) => (v === null || v === undefined || v === "" ? "—" : String(v));
  return (
    <details open>
      <summary>Änderungen{total > changes.length ? ` (die ersten ${changes.length} von ${total})` : ` (${total})`}</summary>
      <div style={{ overflowX: "auto" }}>
        <table className="data">
          <thead><tr>{changes[0].sheet !== undefined && <th>Blatt</th>}<th>Zeile</th><th>Schlüssel</th><th>Spalte</th><th>Alt</th><th>Neu</th></tr></thead>
          <tbody>
            {changes.map((c, i) => (
              <tr key={i}>
                {c.sheet !== undefined && <td>{c.sheet}</td>}
                <td>{c.row}</td><td>{c.key}</td><td>{c.column}</td><td>{show(c.old)}</td><td><b>{show(c.new)}</b></td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </details>
  );
}

function useRunner() {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [preview, setPreview] = useState<any>(null); // eslint-disable-line @typescript-eslint/no-explicit-any
  const [done, setDone] = useState(false);

  const run = async (path: string, source: File, target: File, config: unknown, apply: boolean) => {
    setBusy(true);
    setError("");
    try {
      const form = new FormData();
      form.append("source", source);
      form.append("target", target);
      form.append("config", JSON.stringify(config));
      form.append("apply", String(apply));
      if (!apply) {
        setPreview(await upload(`/api/exceltools/${path}`, form));
        setDone(false);
        return;
      }
      // Die fertige Datei kommt als Download; fetchFile sendet JSON, hier brauchen wir Formulardaten.
      const response = await fetch(`/api/exceltools/${path}`, { method: "POST", body: form, credentials: "same-origin" });
      if (!response.ok) {
        let message = response.statusText;
        try { const d = await response.json(); message = typeof d.detail === "string" ? d.detail : message; } catch { /* kein JSON */ }
        throw new Error(message);
      }
      const header = response.headers.get("content-disposition") ?? "";
      const m = /filename\*=UTF-8''([^;]+)/i.exec(header);
      saveBlob({ blob: await response.blob(), filename: m ? decodeURIComponent(m[1]) : target.name });
      setDone(true);
    } catch (e) {
      setError(errorText(e));
    } finally {
      setBusy(false);
    }
  };
  const reset = () => { setPreview(null); setDone(false); };
  return { busy, error, preview, done, run, reset };
}

/* ---------- Werkzeug 1 ---------- */

function TransferTool() {
  const source = useWorkbook();
  const target = useWorkbook();
  const [sourceKey, setSourceKey] = useState("");
  const [targetKey, setTargetKey] = useState("");
  const [take, setTake] = useState<Record<string, { on: boolean; name: string }>>({});
  const [overwrite, setOverwrite] = useState<"always" | "empty">("always");
  const [skipEmpty, setSkipEmpty] = useState(true);
  const runner = useRunner();
  const { reset } = runner;

  const sourceCols = source.columns.join("\n");
  const targetCols = target.columns.join("\n");
  useEffect(() => {
    setSourceKey(pickKey(source.columns));
    setTake(Object.fromEntries(source.columns.map((c) => [c, { on: false, name: c }])));
    reset();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [sourceCols, source.sheet]);
  useEffect(() => { setTargetKey(pickKey(target.columns)); reset(); /* eslint-disable-next-line react-hooks/exhaustive-deps */ }, [targetCols, target.sheet]);
  useEffect(() => { reset(); /* eslint-disable-next-line react-hooks/exhaustive-deps */ }, [sourceKey, targetKey, take, overwrite, skipEmpty, source.file, target.file]);

  const config = useMemo(() => ({
    source_sheet: source.sheet, source_header: source.header, source_key: sourceKey,
    target_sheet: target.sheet, target_header: target.header, target_key: targetKey,
    pairs: Object.entries(take).filter(([, v]) => v.on).map(([c, v]) => ({ source: c, target: v.name })),
    overwrite, skip_empty: skipEmpty,
  }), [source.sheet, source.header, target.sheet, target.header, sourceKey, targetKey, take, overwrite, skipEmpty]);
  const ready = !!(source.file && target.file && sourceKey && targetKey && config.pairs.length);
  const p = runner.preview;

  return (
    <>
      <p className="muted">
        Zwei Excel-Tabellen: Aus der <b>Quelle</b> werden gewählte Spalten in die <b>Zieldatei</b> übertragen. Die Zeilen werden über eine
        Schlüsselspalte (z. B. Kabelnummer) einander zugeordnet. Du lädst die Dateien nur hoch; sie werden auf dem Server nicht gespeichert.
      </p>
      <div className="tool-grid">
        <FileBox title="Quelle (von hier kommen die Werte)" wb={source} />
        <FileBox title="Ziel (hier werden Werte geändert)" wb={target} hint="Die Zieldatei wird als neue Datei zum Download erzeugt, das Original bleibt unverändert." />
      </div>
      {source.columns.length > 0 && target.columns.length > 0 && (
        <fieldset className="card settings">
          <legend>Zuordnung</legend>
          <div className="grid2">
            <Select label="Schlüsselspalte in der Quelle" value={sourceKey} onChange={setSourceKey} options={source.columns} />
            <Select label="Schlüsselspalte im Ziel" value={targetKey} onChange={setTargetKey} options={target.columns} />
          </div>
          <p className="muted">Spalten, die übertragen werden sollen (rechts: Name der Spalte im Ziel; gibt es sie dort nicht, wird sie neu angelegt):</p>
          <datalist id="target-cols">{target.columns.map((c) => <option key={c} value={c} />)}</datalist>
          <ul className="plain">
            {source.columns.filter((c) => c !== sourceKey).map((c) => (
              <li key={c} className="inline-form">
                <label className="check">
                  <input type="checkbox" checked={take[c]?.on ?? false}
                    onChange={(e) => setTake({ ...take, [c]: { name: take[c]?.name ?? c, on: e.target.checked } })} />
                  {c}
                </label>
                <span>→</span>
                <input list="target-cols" value={take[c]?.name ?? c} disabled={!take[c]?.on}
                  onChange={(e) => setTake({ ...take, [c]: { on: true, name: e.target.value } })} />
              </li>
            ))}
          </ul>
          <label className="check"><input type="checkbox" checked={skipEmpty} onChange={(e) => setSkipEmpty(e.target.checked)} />
            Leere Werte der Quelle überschreiben nichts</label>
          <label className="check"><input type="checkbox" checked={overwrite === "empty"} onChange={(e) => setOverwrite(e.target.checked ? "empty" : "always")} />
            Nur leere Zellen im Ziel füllen (vorhandene Werte bleiben)</label>
          <div className="row-buttons">
            <button disabled={runner.busy || !ready} onClick={() => void runner.run("transfer", source.file!, target.file!, config, false)}>
              {runner.busy ? "Bitte warten …" : "Vorschau"}
            </button>
            <button className="primary" disabled={runner.busy || !ready || !p}
              title={p ? "" : "Erst die Vorschau ansehen"}
              onClick={() => void runner.run("transfer", source.file!, target.file!, config, true)}>Ausführen und Datei laden</button>
          </div>
        </fieldset>
      )}
      {runner.error && <p className="error">{runner.error}</p>}
      {runner.done && <div className="banner ok-banner">Fertig – die geänderte Zieldatei wurde heruntergeladen.</div>}
      {p && (
        <div className="banner warn"><div>
          <b>Vorschau – noch nichts geändert</b>
          <ul className="plain">
            <li><b>{p.rows_matched}</b> Zeilen im Ziel mit passendem Schlüssel, davon <b>{p.rows_changed}</b> mit Änderung</li>
            <li><b>{p.cells_changed}</b> Zellen werden geändert, {p.cells_unchanged} sind schon gleich{p.cells_kept ? `, ${p.cells_kept} bleiben (waren nicht leer)` : ""}</li>
            {p.new_columns.length > 0 && <li>Neue Spalten im Ziel: {p.new_columns.join(", ")}</li>}
            {p.cells_merged_skipped > 0 && <li className="warn">{p.cells_merged_skipped} Zellen sind verbunden und werden übersprungen</li>}
          </ul>
          <List title="Schlüssel im Ziel, die in der Quelle fehlen (bleiben unverändert)" items={p.missing_in_source} total={p.missing_in_source_total} />
          <List title="Schlüssel nur in der Quelle (kommen im Ziel nicht vor)" items={p.only_in_source} total={p.only_in_source_total} />
          <List title="Schlüssel mehrfach in der Quelle (nur die erste Zeile gilt)" items={p.duplicate_keys} total={p.duplicate_total} />
          <Changes changes={p.changes} total={p.cells_changed} />
        </div></div>
      )}
    </>
  );
}

/* ---------- Werkzeug 2 ---------- */

function FillTool() {
  const source = useWorkbook();
  const target = useWorkbook();
  const [sourceKey, setSourceKey] = useState("");
  const [sourceValue, setSourceValue] = useState("");
  const [targetColumn, setTargetColumn] = useState("");
  const [keyColumn, setKeyColumn] = useState("");
  const [overwrite, setOverwrite] = useState<"always" | "empty">("always");
  const [skipEmpty, setSkipEmpty] = useState(true);
  const runner = useRunner();
  const { reset } = runner;

  const sourceCols = source.columns.join("\n");
  useEffect(() => {
    setSourceKey(pickKey(source.columns));
    setSourceValue(source.columns.find((c) => c !== pickKey(source.columns)) ?? "");
    reset();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [sourceCols, source.sheet]);
  useEffect(() => { reset(); /* eslint-disable-next-line react-hooks/exhaustive-deps */ }, [sourceKey, sourceValue, targetColumn, keyColumn, overwrite, skipEmpty, source.file, target.file, target.header]);

  const targetNames = useMemo(() => [...new Set(target.sheets.flatMap((s) => s.columns.map((c) => c.name)))], [target.sheets]);
  const config = {
    source_sheet: source.sheet, source_header: source.header, source_key: sourceKey, source_value: sourceValue,
    target_header: target.header, target_column: targetColumn, target_key_column: keyColumn, target_sheets: [] as string[],
    overwrite, skip_empty: skipEmpty,
  };
  const ready = !!(source.file && target.file && sourceKey && sourceValue && targetColumn.trim());
  const p = runner.preview;

  return (
    <>
      <p className="muted">
        Aus der <b>Quelle</b> werden Schlüssel (z. B. Kabelnummer) und Wert aus je einer Spalte genommen. Jeder Schlüssel wird in der
        <b> Zieldatei auf allen Blättern</b> gesucht. Wo er steht, wird der Wert in der gewählten Spalte derselben Zeile eingetragen.
      </p>
      <div className="tool-grid">
        <FileBox title="Quelle (Schlüssel und Wert)" wb={source} />
        <FileBox title="Ziel (hier wird gesucht und eingetragen)" wb={target} allSheets
          hint="Die Überschriften der Zielspalten werden in dieser Zeile auf jedem Blatt gesucht. Die Zieldatei wird als neue Datei zum Download erzeugt." />
      </div>
      {source.columns.length > 0 && target.file && (
        <fieldset className="card settings">
          <legend>Zuordnung</legend>
          <div className="grid2">
            <Select label="Schlüsselspalte in der Quelle" value={sourceKey} onChange={setSourceKey} options={source.columns} />
            <Select label="Wertspalte in der Quelle" value={sourceValue} onChange={setSourceValue} options={source.columns} />
            <label>Zielspalte (Name oder Buchstabe, z. B. „Länge“ oder „F“)
              <input list="fill-target-cols" value={targetColumn} onChange={(e) => setTargetColumn(e.target.value)} />
              <datalist id="fill-target-cols">{targetNames.map((c) => <option key={c} value={c} />)}</datalist>
            </label>
            <label>Schlüssel im Ziel suchen in
              <input list="fill-target-cols" placeholder="allen Zellen" value={keyColumn} onChange={(e) => setKeyColumn(e.target.value)} />
            </label>
          </div>
          <p className="muted">
            Gefunden wird eine Zelle, deren gesamter Inhalt dem Schlüssel entspricht (Groß-/Kleinschreibung und Leerzeichen am Rand egal).
            Blätter ohne die Zielspalte werden übersprungen. Leer lassen bei „Schlüssel suchen in“ = alle Zellen.
          </p>
          <label className="check"><input type="checkbox" checked={skipEmpty} onChange={(e) => setSkipEmpty(e.target.checked)} />
            Schlüssel ohne Wert in der Quelle ignorieren</label>
          <label className="check"><input type="checkbox" checked={overwrite === "empty"} onChange={(e) => setOverwrite(e.target.checked ? "empty" : "always")} />
            Nur leere Zellen im Ziel füllen (vorhandene Werte bleiben)</label>
          <div className="row-buttons">
            <button disabled={runner.busy || !ready} onClick={() => void runner.run("fill", source.file!, target.file!, config, false)}>
              {runner.busy ? "Bitte warten …" : "Vorschau"}
            </button>
            <button className="primary" disabled={runner.busy || !ready || !p}
              title={p ? "" : "Erst die Vorschau ansehen"}
              onClick={() => void runner.run("fill", source.file!, target.file!, config, true)}>Ausführen und Datei laden</button>
          </div>
        </fieldset>
      )}
      {runner.error && <p className="error">{runner.error}</p>}
      {runner.done && <div className="banner ok-banner">Fertig – die geänderte Zieldatei wurde heruntergeladen.</div>}
      {p && (
        <div className="banner warn"><div>
          <b>Vorschau – noch nichts geändert</b>
          <ul className="plain">
            <li><b>{p.keys_found}</b> von {p.keys_total} Schlüsseln in der Zieldatei gefunden{p.found_multiple ? `, davon ${p.found_multiple} an mehreren Stellen (alle werden gesetzt)` : ""}</li>
            <li><b>{p.cells_changed}</b> Zellen werden geändert, {p.cells_unchanged} sind schon gleich{p.cells_kept ? `, ${p.cells_kept} bleiben (waren nicht leer)` : ""}</li>
            {p.sheets.map((s: { sheet: string; found: number; column: string }) => <li key={s.sheet} className="muted">Blatt „{s.sheet}“: {s.found} Treffer, Spalte {s.column}</li>)}
            {p.sheets_skipped.length > 0 && <li className="warn">Ohne passende Spalte übersprungen: {p.sheets_skipped.join(", ")}</li>}
            {p.row_clash > 0 && <li className="warn">{p.row_clash} Zeilen enthalten mehrere verschiedene Schlüssel (der erste gilt)</li>}
            {p.cells_merged_skipped > 0 && <li className="warn">{p.cells_merged_skipped} Zellen sind verbunden und werden übersprungen</li>}
          </ul>
          <List title="Schlüssel nicht in der Zieldatei gefunden" items={p.not_found} total={p.not_found_total} />
          <List title="Schlüssel ohne Wert in der Quelle" items={p.empty_value} total={p.empty_value_total} />
          <List title="Schlüssel mehrfach in der Quelle (nur die erste Zeile gilt)" items={p.duplicate_keys} total={p.duplicate_total} />
          <Changes changes={p.changes} total={p.cells_changed} />
        </div></div>
      )}
    </>
  );
}

export function ExcelToolsPage() {
  const [tab, setTab] = useState<"transfer" | "fill">("transfer");
  return (
    <div>
      <h1>Excel-Werkzeuge</h1>
      <div className="tabs">
        <button className={tab === "transfer" ? "active" : ""} onClick={() => setTab("transfer")}>Spalten übertragen</button>
        <button className={tab === "fill" ? "active" : ""} onClick={() => setTab("fill")}>Schlüssel suchen &amp; Wert eintragen</button>
      </div>
      {tab === "transfer" ? <TransferTool /> : <FillTool />}
    </div>
  );
}
