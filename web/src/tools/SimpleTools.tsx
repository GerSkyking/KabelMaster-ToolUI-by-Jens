// Einzelsuche, Stapelsuche und Farbmarkierung.
import { useState } from "react";
import {
  ColumnPanel, Config, FormatChoice, GlobalFieldsPanel, Notice, OutputPanel, ResultTable, TablePayload, TemplateBar,
  TermList, requestBody, useDebounced, useGlobals, useRequestKey, useToolApi, useToolConfig,
} from "./common";
import type { ToolProps } from "./types";

function useSetup({ datasetId, columns, creator }: ToolProps, tab: string) {
  const cfg = useToolConfig(datasetId, tab, columns);
  const [globals, setGlobals] = useGlobals(creator);
  return { ...cfg, globals, setGlobals };
}

export function SearchTool(props: ToolProps) {
  const { config, update, replace, globals, setGlobals } = useSetup(props, "single_search");
  const api = useToolApi(props.backend, props.datasetId, "search");
  const [term, setTerm] = useState("");
  const [formats, setFormats] = useState(["xlsx"]);
  const [table, setTable] = useState<TablePayload | null>(null);
  const key = useRequestKey(config, term);

  useDebounced(() => {
    if (term.trim().length < 3) return setTable(null);
    void api.preview<{ table: TablePayload }>(requestBody(config, globals, { term })).then((r) => r && setTable(r.table));
  }, [key]);

  return (
    <div className="tool">
      <TemplateBar tabId="single_search" config={config} columns={props.columns} onApply={replace} />
      <GlobalFieldsPanel globals={globals} onChange={setGlobals} />
      <div className="tool-grid">
        <div>
          <ColumnPanel config={config} update={update} />
          <OutputPanel config={config} update={update} />
        </div>
        <section className="card">
          <div className="inline-form">
            <input type="search" className="wide" placeholder="Suchbegriff (mind. 3 Zeichen)" value={term} onChange={(e) => setTerm(e.target.value)} />
            <FormatChoice formats={formats} onChange={setFormats} />
            <button className="primary" disabled={api.busy || term.trim().length < 3 || !formats.length}
              onClick={() => void api.exportFile(requestBody(config, globals, { term, formats }), "Suche")}>Exportieren</button>
          </div>
          <Notice error={api.error} />
          <ResultTable table={table} />
        </section>
      </div>
    </div>
  );
}

export function BatchTool(props: ToolProps) {
  const { config, update, replace, globals, setGlobals } = useSetup(props, "batch_search");
  const api = useToolApi(props.backend, props.datasetId, "batch");
  const [formats, setFormats] = useState(["xlsx"]);
  const [picked, setPicked] = useState("");
  const [counts, setCounts] = useState<Record<string, number>>({});
  const [table, setTable] = useState<TablePayload | null>(null);
  const batch = config.batch;
  const key = useRequestKey(config, picked);

  useDebounced(() => {
    void api.preview<{ terms: { term: string; count: number }[]; table?: TablePayload }>(requestBody(config, globals, { term: picked })).then((r) => {
      if (!r) return;
      setCounts(Object.fromEntries(r.terms.map((t) => [t.term, t.count])));
      setTable(r.table ?? null);
    });
  }, [key]);

  const active = (config.batch_search_terms as { enabled: boolean }[]).filter((t) => t.enabled).length;
  return (
    <div className="tool">
      <TemplateBar tabId="batch_search" config={config} columns={props.columns} onApply={replace} />
      <GlobalFieldsPanel globals={globals} onChange={setGlobals} />
      <div className="tool-grid">
        <div>
          <section className="card">
            <h3>Suchbegriffe</h3>
            <TermList terms={config.batch_search_terms} onChange={(t) => update({ batch_search_terms: t })} onPick={(t) => setPicked(t === picked ? "" : t)} picked={picked} counts={counts} />
            <div className="fields">
              <label className="check"><input type="checkbox" checked={batch.result_column_enabled}
                onChange={(e) => update({ batch: { ...batch, result_column_enabled: e.target.checked } })} />Ergebnis-Spalte (tatsächlich getroffene Werte)</label>
              <label>Spaltenname<input value={batch.result_column_name} onChange={(e) => update({ batch: { ...batch, result_column_name: e.target.value } })} /></label>
              <label>Trennzeichen<input value={batch.separator} onChange={(e) => update({ batch: { ...batch, separator: e.target.value } })} /></label>
            </div>
          </section>
          <ColumnPanel config={config} update={update} />
          <OutputPanel config={config} update={update} />
        </div>
        <section className="card">
          <div className="inline-form">
            <FormatChoice formats={formats} onChange={setFormats} />
            <button className="primary" disabled={api.busy || !active || !formats.length}
              onClick={() => void api.exportFile(requestBody(config, globals, { formats }), "Stapelsuche")}>Alle {active} Begriffe exportieren (ZIP)</button>
            {picked && <button disabled={api.busy || !formats.length}
              onClick={() => void api.exportFile(requestBody(config, globals, { formats, term: picked }), picked)}>Nur „{picked}“</button>}
          </div>
          <Notice error={api.error} />
          {picked ? <ResultTable table={table} /> : <p className="muted">Begriff anklicken, um die Treffer zu sehen.</p>}
        </section>
      </div>
    </div>
  );
}

export function HighlightTool(props: ToolProps) {
  const { config, update, replace, globals, setGlobals } = useSetup(props, "highlight");
  const api = useToolApi(props.backend, props.datasetId, "highlight");
  const [formats, setFormats] = useState(["xlsx"]);
  const [table, setTable] = useState<TablePayload | null>(null);
  const key = useRequestKey(config);
  const colors: Config[] = config.colors;
  const ccols: Config[] = config.color_columns;
  const terms: Config[] = config.color_search_terms;

  useDebounced(() => {
    void api.preview<{ table: TablePayload }>(requestBody(config, globals)).then((r) => r && setTable(r.table));
  }, [key]);

  const nextId = (list: Config[]) => Math.max(0, ...list.map((c) => c.id)) + 1;
  const setColor = (id: number, change: Config) => update({ colors: colors.map((c) => (c.id === id ? { ...c, ...change } : c)) });
  const setTerm = (i: number, change: Config) => update({ color_search_terms: terms.map((t, j) => (j === i ? { ...t, ...change } : t)) });
  const [bulk, setBulk] = useState("");
  const [bulkColor, setBulkColor] = useState(colors[0]?.id ?? 1);

  return (
    <div className="tool">
      <TemplateBar tabId="highlight" config={config} columns={props.columns} onApply={replace} />
      <GlobalFieldsPanel globals={globals} onChange={setGlobals} />
      <div className="tool-grid">
        <div>
          <section className="card">
            <h3>Farben</h3>
            {colors.map((c) => (
              <div className="inline-form" key={c.id}>
                <input type="color" value={c.color_hex} onChange={(e) => setColor(c.id, { color_hex: e.target.value })} />
                <input value={c.name} onChange={(e) => setColor(c.id, { name: e.target.value })} />
                <label>Deckkraft<input type="range" min={0} max={100} value={100 - c.alpha} onChange={(e) => setColor(c.id, { alpha: 100 - Number(e.target.value) })} /></label>
                <select value={c.column_id ?? ""} onChange={(e) => setColor(c.id, { column_id: e.target.value ? Number(e.target.value) : null })}>
                  <option value="">– keine Farbspalte –</option>
                  {ccols.map((cc) => <option key={cc.id} value={cc.id}>{cc.name}</option>)}
                </select>
                <button className="link" onClick={() => update({ colors: colors.filter((x) => x.id !== c.id), color_search_terms: terms.filter((t) => t.color_id !== c.id) })}>✕</button>
              </div>
            ))}
            <button onClick={() => update({ colors: [...colors, { id: nextId(colors), name: `Farbe ${colors.length + 1}`, color_hex: "#00AAFF", alpha: 30, column_id: null }] })}>+ Farbe</button>
          </section>
          <section className="card">
            <h3>Farbspalten (zusätzliche Ausgabespalten mit dem Farbnamen)</h3>
            {ccols.map((cc) => (
              <div className="inline-form" key={cc.id}>
                <input value={cc.name} onChange={(e) => update({ color_columns: ccols.map((x) => (x.id === cc.id ? { ...x, name: e.target.value } : x)) })} />
                <button className="link" onClick={() => update({ color_columns: ccols.filter((x) => x.id !== cc.id), colors: colors.map((c) => (c.column_id === cc.id ? { ...c, column_id: null } : c)) })}>✕</button>
              </div>
            ))}
            <button onClick={() => update({ color_columns: [...ccols, { id: nextId(ccols), name: `Farbe ${ccols.length + 1}`, width_px: 100 }] })}>+ Farbspalte</button>
          </section>
          <section className="card">
            <h3>Suchbegriffe mit Farbe</h3>
            <div className="inline-form">
              <textarea rows={2} placeholder="Begriffe (eine Zeile pro Begriff)" value={bulk} onChange={(e) => setBulk(e.target.value)} />
              <select value={bulkColor} onChange={(e) => setBulkColor(Number(e.target.value))}>{colors.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}</select>
              <button disabled={!bulk.trim()} onClick={() => {
                const add = bulk.split(/\r?\n/).map((t) => t.trim()).filter(Boolean).map((term) => ({ term, enabled: true, color_id: bulkColor }));
                update({ color_search_terms: [...terms, ...add] });
                setBulk("");
              }}>Hinzufügen</button>
            </div>
            <ul className="plain terms">
              {terms.map((t, i) => (
                <li key={i}>
                  <input type="checkbox" checked={t.enabled} onChange={(e) => setTerm(i, { enabled: e.target.checked })} />
                  <span>{t.term}</span>
                  <select value={t.color_id} onChange={(e) => setTerm(i, { color_id: Number(e.target.value) })}>{colors.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}</select>
                  <button className="link" onClick={() => update({ color_search_terms: terms.filter((_, j) => j !== i) })}>✕</button>
                </li>
              ))}
            </ul>
            <label>Ganze Zeile färben ab Treffern gleicher Farbe
              <input type="number" min={1} className="narrow" value={config.color_min_matches} onChange={(e) => update({ color_min_matches: Number(e.target.value) })} />
            </label>
          </section>
          <ColumnPanel config={config} update={update} />
          <OutputPanel config={config} update={update} />
        </div>
        <section className="card">
          <div className="inline-form">
            <FormatChoice formats={formats} onChange={setFormats} />
            <button className="primary" disabled={api.busy || !formats.length}
              onClick={() => void api.exportFile(requestBody(config, globals, { formats }), "Farbmarkierung")}>Exportieren</button>
          </div>
          <Notice error={api.error} />
          <ResultTable table={table} />
        </section>
      </div>
    </div>
  );
}
