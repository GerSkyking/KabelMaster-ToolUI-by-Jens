// Schrank-Erkennung: Muster, erkannte Schränke, Einzel- oder Sammeldatei.
import { useEffect, useMemo, useState } from "react";
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
  const [view, setView] = useState<"settings" | "cabinets">(() => {
    try { return localStorage.getItem("cabinet-view") === "cabinets" ? "cabinets" : "settings"; } catch { return "settings"; }
  });
  const [cabQuery, setCabQuery] = useState("");
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
  }, [key], view === "cabinets" ? 120 : 500);

  const changeView = (v: "settings" | "cabinets") => {
    setView(v);
    try { localStorage.setItem("cabinet-view", v); } catch { /* Speicher gesperrt */ }
  };

  // Schrank-Ansicht: immer ein Schrank gewählt, damit rechts direkt die Tabelle steht
  useEffect(() => {
    if (view === "cabinets" && cabinets.length && !cabinets.some((c) => c.name === picked)) setPicked(cabinets[0].name);
  }, [view, cabinets, picked]);
  const shownCabinets = useMemo(() => {
    const q = cabQuery.trim().toLowerCase();
    return q ? cabinets.filter((c) => c.name.toLowerCase().includes(q)) : cabinets;
  }, [cabinets, cabQuery]);
  const moveSelection = (delta: number) => {
    if (!shownCabinets.length) return;
    const i = shownCabinets.findIndex((c) => c.name === picked);
    setPicked(shownCabinets[Math.min(Math.max(i + delta, 0), shownCabinets.length - 1)].name);
  };

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
      <div className="tabs sub-tabs" role="tablist">
        <button role="tab" aria-selected={view === "settings"} className={view === "settings" ? "active" : ""} onClick={() => changeView("settings")}>Einstellungen &amp; Export</button>
        <button role="tab" aria-selected={view === "cabinets"} className={view === "cabinets" ? "active" : ""} onClick={() => changeView("cabinets")}>
          Schränke ansehen{cabinets.length ? ` (${cabinets.length})` : ""}
        </button>
      </div>
      {view === "cabinets" ? (
        <div className="cab-split">
          <aside className="card cab-list"
            onKeyDown={(e) => {
              if (e.key === "ArrowDown" || e.key === "ArrowUp") { e.preventDefault(); moveSelection(e.key === "ArrowDown" ? 1 : -1); }
            }}>
            <input type="search" placeholder="Schrank suchen …" value={cabQuery} onChange={(e) => setCabQuery(e.target.value)} />
            <ul className="plain">
              {shownCabinets.map((c) => (
                <li key={c.name}>
                  <button className={picked === c.name ? "active" : ""} aria-current={picked === c.name} onClick={() => setPicked(c.name)}>
                    <span>{c.name}</span><span className="chip">{c.count}</span>
                  </button>
                </li>
              ))}
            </ul>
            {!shownCabinets.length && <p className="muted">{cabinets.length ? "Kein Treffer." : "Keine Schränke erkannt. Muster unter „Einstellungen & Export“ prüfen."}</p>}
          </aside>
          <section className="card cab-table">
            {picked ? <><h3>Schrank {picked}</h3><ResultTable table={table} /></> : <p className="muted">Schrank links auswählen.</p>}
            <Notice error={api.error} />
          </section>
        </div>
      ) : (
      <>
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
      </>
      )}
    </div>
  );
}
