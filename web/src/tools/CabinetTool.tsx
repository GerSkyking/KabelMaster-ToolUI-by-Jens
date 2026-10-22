// Schrank-Erkennung: Muster, erkannte Schränke, Einzel- oder Sammeldatei.
import { useState } from "react";
import {
  ColumnPanel, Config, FormatChoice, GlobalFieldsPanel, Notice, OutputPanel, ResultTable, TablePayload, TemplateBar,
  requestBody, useDebounced, useGlobals, useRequestKey, useToolApi, useToolConfig,
} from "./common";
import type { ToolProps } from "./types";

interface Format { pattern: string; enabled: boolean; with_field: boolean }

export function CabinetTool(props: ToolProps) {
  const { config, update, replace } = useToolConfig(props.datasetId, "cabinet", props.columns);
  const [globals, setGlobals] = useGlobals(props.creator);
  const api = useToolApi(props.backend, props.datasetId, "cabinet");
  const [formats, setFormats] = useState(["xlsx"]);
  const [cabinets, setCabinets] = useState<{ name: string; count: number }[]>([]);
  const [skipped, setSkipped] = useState<Set<string>>(new Set());
  const [picked, setPicked] = useState("");
  const [table, setTable] = useState<TablePayload | null>(null);
  const cab: Config = config.cabinet_config;
  const setCab = (change: Config) => update({ cabinet_config: { ...cab, ...change } });
  const list: Format[] = cab.formats;
  const key = useRequestKey(config, picked);

  useDebounced(() => {
    void api.preview<{ cabinets: { name: string; count: number }[]; table?: TablePayload }>(requestBody(config, globals, { term: picked })).then((r) => {
      if (!r) return;
      setCabinets(r.cabinets);
      setTable(r.table ?? null);
    });
  }, [key]);

  const chosen = cabinets.map((c) => c.name).filter((n) => !skipped.has(n));
  const toggle = (name: string) => setSkipped((s) => {
    const next = new Set(s);
    if (!next.delete(name)) next.add(name);
    return next;
  });
  const setFormat = (i: number, change: Partial<Format>) => setCab({ formats: list.map((f, j) => (j === i ? { ...f, ...change } : f)) });
  const exportAll = (combined: boolean) =>
    api.exportFile(requestBody(config, globals, { formats, cabinets: chosen, combined }), combined ? "Sammeldatei" : "Schraenke");

  return (
    <div className="tool">
      <TemplateBar tabId="cabinet" config={config} columns={props.columns} onApply={replace} />
      <GlobalFieldsPanel globals={globals} onChange={setGlobals} />
      <div className="tool-grid">
        <div>
          <section className="card">
            <h3>Muster</h3>
            <p className="muted"><code>X</code> = Schrank, <code>x</code> = Feld (anzeigen), <code>y</code> = egal, alles andere muss genau so im Text stehen. Beispiel: <code>xx+XX</code> findet <code>=E05+SC15-X130</code>.</p>
            {list.map((f, i) => (
              <div className="inline-form" key={i}>
                <input type="checkbox" checked={f.enabled} onChange={(e) => setFormat(i, { enabled: e.target.checked })} />
                <input value={f.pattern} onChange={(e) => setFormat(i, { pattern: e.target.value })} className="narrow" />
                <label className="check"><input type="checkbox" checked={f.with_field} onChange={(e) => setFormat(i, { with_field: e.target.checked })} />Feld mit ausgeben</label>
                <button className="link" onClick={() => setCab({ formats: list.filter((_, j) => j !== i) })}>✕</button>
              </div>
            ))}
            <button onClick={() => setCab({ formats: [...list, { pattern: "XX", enabled: true, with_field: false }] })}>+ Muster</button>
            <div className="fields">
              <label className="check"><input type="checkbox" checked={cab.cabinet_column} onChange={(e) => setCab({ cabinet_column: e.target.checked })} />Spalte „Schrank“ ausgeben</label>
              {["E", "J", "H"].map((l) => (
                <label className="check" key={l}><input type="checkbox" checked={!!cab.fields?.[l]} onChange={(e) => setCab({ fields: { ...cab.fields, [l]: e.target.checked } })} />{l}-Feld</label>
              ))}
              <label>Eigene Felder (Komma)<input value={cab.custom_fields} onChange={(e) => setCab({ custom_fields: e.target.value })} placeholder="K, E00" /></label>
            </div>
          </section>
          <ColumnPanel config={config} update={update} />
          <OutputPanel config={config} update={update} />
        </div>
        <div>
          <section className="card">
            <h3>Erkannte Schränke ({cabinets.length})</h3>
            <div className="inline-form">
              <button onClick={() => setSkipped(new Set())}>Alle wählen</button>
              <button onClick={() => setSkipped(new Set(cabinets.map((c) => c.name)))}>Keine</button>
              <FormatChoice formats={formats} onChange={setFormats} />
              <button disabled={api.busy || !chosen.length || !formats.length} onClick={() => void exportAll(false)}>Je Schrank exportieren</button>
              <button className="primary" disabled={api.busy || !chosen.length || !formats.length} onClick={() => void exportAll(true)}>Sammeldatei</button>
            </div>
            <Notice error={api.error} />
            <ul className="plain terms">
              {cabinets.map((c) => (
                <li key={c.name} className={picked === c.name ? "picked" : ""}>
                  <input type="checkbox" checked={!skipped.has(c.name)} onChange={() => toggle(c.name)} />
                  <button className="link" onClick={() => setPicked(picked === c.name ? "" : c.name)}>{c.name}</button>
                  <span className="chip">{c.count} Zeilen</span>
                </li>
              ))}
            </ul>
          </section>
          {picked && <section className="card"><h3>Schrank {picked}</h3><ResultTable table={table} /></section>}
        </div>
      </div>
    </div>
  );
}
