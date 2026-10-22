// KMK: Beschrifter-Vorschau, Export (PDF/Excel) und Abhaken "beschriftet Ziel 1/2".
import { useCallback, useEffect, useState } from "react";
import { api, errorText } from "../api";
import { syncDataset } from "../sync";
import {
  ColumnCfg, ColumnPanel, Config, FormatChoice, GlobalFieldsPanel, Notice, TemplateBar, TermList, requestBody,
  useDebounced, useGlobals, useRequestKey, useToolApi, useToolConfig,
} from "./common";
import type { ToolProps } from "./types";

interface Preview {
  groups: { title: string; count: number; labels: { lines: string[]; row_id: number | null }[] }[];
  labels: number;
  row_ids: number[];
  warnings: string[];
}
interface Run {
  id: number; created_by: string; created_at: string; formats: string[]; count: number; note: string;
  status: Record<string, string>;
}

type Mode = "ask" | "auto" | "later";
const MODE_KEY = "uwkm:kmk-mode";
const TARGET_LABEL: Record<string, string> = { "1": "Ziel 1", "2": "Ziel 2", both: "Ziel 1 + Ziel 2" };

function readMode(): { mode: Mode; target: string } {
  try {
    const saved = JSON.parse(localStorage.getItem(MODE_KEY) ?? "null");
    if (saved?.mode) return saved;
  } catch {
    /* ignorieren */
  }
  return { mode: "ask", target: "both" };
}

function labelContent(config: Config): { order: string[]; enabled: Record<string, boolean> } {
  const cols: ColumnCfg[] = config.columns;
  const content = config.kmk_config.label_content ?? {};
  const names = cols.map((c) => c.name);
  const order: string[] = [...(content.order ?? []).filter((n: string) => names.includes(n)), ...names.filter((n) => !(content.order ?? []).includes(n))];
  const enabled: Record<string, boolean> = { ...(content.enabled ?? {}) };
  // Ohne gespeicherte Auswahl: nur die ersten beiden Ausgabespalten (Schilder sind klein)
  if (!content.order) [...cols].sort((a, b) => a.output_order - b.output_order).forEach((c, i) => { enabled[c.name] = c.output_enabled && i < 2; });
  const fallbackOrder = content.order ? order : [...cols].sort((a, b) => a.output_order - b.output_order).map((c) => c.name);
  return { order: fallbackOrder, enabled };
}

export function KmkTool(props: ToolProps) {
  const { datasetId, backend, columns, creator } = props;
  const { config, update, replace } = useToolConfig(datasetId, "kmk", columns);
  const [globals, setGlobals] = useGlobals(creator);
  const toolApi = useToolApi(backend, datasetId, "kmk");
  const [formats, setFormats] = useState(["pdf"]);
  const [preview, setPreview] = useState<Preview | null>(null);
  const [hideLabeled, setHideLabeled] = useState("");
  const [prefs, setPrefs] = useState(readMode);
  const [runs, setRuns] = useState<Run[]>([]);
  const [dialogRun, setDialogRun] = useState<Run | null>(null);
  const [message, setMessage] = useState("");
  const kmk = config.kmk_config;
  const setKmk = (change: Config) => update({ kmk_config: { ...kmk, ...change } });
  const content = labelContent(config);
  const key = useRequestKey(config, hideLabeled);

  const effectiveConfig = (): Config => ({
    ...config,
    kmk_config: { ...kmk, label_content: { order: content.order, enabled: content.enabled } },
  });

  const loadRuns = useCallback(async () => {
    try {
      setRuns(await api<Run[]>(`/api/datasets/${datasetId}/kmk/runs`));
    } catch (e) {
      setMessage(errorText(e));
    }
  }, [datasetId]);
  useEffect(() => void loadRuns(), [loadRuns]);
  useEffect(() => {
    try {
      localStorage.setItem(MODE_KEY, JSON.stringify(prefs));
    } catch {
      /* ignorieren */
    }
  }, [prefs]);

  useDebounced(() => {
    void toolApi.preview<Preview>(requestBody(effectiveConfig(), globals, { hide_labeled: hideLabeled })).then((r) => r && setPreview(r));
  }, [key]);

  const doExport = async () => {
    setMessage("");
    const auto = prefs.mode === "auto";
    const file = await toolApi.exportFile(
      requestBody(effectiveConfig(), globals, { formats, hide_labeled: hideLabeled, mark: auto ? prefs.target : "" }), "KMK");
    if (!file) return;
    await loadRuns();
    const runId = Number(file.headers.get("x-run-id"));
    if (auto) {
      setMessage(`Exportiert und ${TARGET_LABEL[prefs.target]} als beschriftet markiert.`);
      await syncDataset(backend).catch(() => undefined);
    } else if (prefs.mode === "ask" && runId) {
      const fresh = await api<Run[]>(`/api/datasets/${datasetId}/kmk/runs`);
      setDialogRun(fresh.find((r) => r.id === runId) ?? null);
    } else {
      setMessage("Exportiert. Das Abhaken kannst du unten bei „Exportläufe“ nachholen.");
    }
  };

  const mark = async (run: Run, target: string, unmark = false) => {
    setMessage("");
    try {
      const targets = target === "both" ? ["1", "2"] : [target];
      const res = await api<{ changed: number }>(`/api/kmk/runs/${run.id}/mark`, { method: "POST", body: { targets, unmark } });
      setMessage(`${res.changed} Kabel ${unmark ? "zurückgesetzt" : "als beschriftet markiert"} (${TARGET_LABEL[target]}).`);
      await syncDataset(backend).catch(() => undefined);
      await loadRuns();
      setDialogRun(null);
    } catch (e) {
      setMessage(errorText(e));
    }
  };

  const setContent = (order: string[], enabled: Record<string, boolean>) => setKmk({ label_content: { order, enabled } });
  const moveContent = (name: string, dir: -1 | 1) => {
    const order = [...content.order];
    const i = order.indexOf(name), j = i + dir;
    if (j < 0 || j >= order.length) return;
    [order[i], order[j]] = [order[j], order[i]];
    setContent(order, content.enabled);
  };

  const noLabelCols = !props.mapping.labeled1 && !props.mapping.labeled2;
  const status = (run: Run) => ["1", "2"].map((t) => `Ziel ${t}: ${run.status?.[t] || "offen"}`).join(" · ");

  return (
    <div className="tool">
      <TemplateBar tabId="kmk" config={effectiveConfig()} columns={columns} onApply={replace} />
      <GlobalFieldsPanel globals={globals} onChange={setGlobals} />
      <div className="tool-grid">
        <div>
          <section className="card">
            <h3>Suchbegriffe (jeder erzeugt eine Gruppe)</h3>
            <TermList terms={config.batch_search_terms} onChange={(t) => update({ batch_search_terms: t })} />
          </section>
          <section className="card">
            <h3>Schild</h3>
            <div className="fields">
              <label>Typ<input value={kmk.kmk_type.name} onChange={(e) => setKmk({ kmk_type: { ...kmk.kmk_type, name: e.target.value } })} /></label>
              <label>Breite (mm)<input type="number" step="0.5" value={kmk.kmk_type.width_mm} onChange={(e) => setKmk({ kmk_type: { ...kmk.kmk_type, width_mm: Number(e.target.value) } })} /></label>
              <label>Höhe (mm)<input type="number" step="0.5" value={kmk.kmk_type.height_mm} onChange={(e) => setKmk({ kmk_type: { ...kmk.kmk_type, height_mm: Number(e.target.value) } })} /></label>
              <label>Schriftgröße (pt)<input type="number" step="0.5" value={kmk.font_size_pt} onChange={(e) => setKmk({ font_size_pt: Number(e.target.value) })} /></label>
              <label className="check"><input type="checkbox" checked={kmk.auto_shrink} onChange={(e) => setKmk({ auto_shrink: e.target.checked })} />Text automatisch verkleinern</label>
              <label>Mindestgröße (pt)<input type="number" step="0.5" value={kmk.min_font_size_pt} onChange={(e) => setKmk({ min_font_size_pt: Number(e.target.value) })} /></label>
              <label className="check"><input type="checkbox" checked={kmk.frame_enabled} onChange={(e) => setKmk({ frame_enabled: e.target.checked })} />Rahmen</label>
              <label>Rahmenfarbe<input type="color" value={kmk.frame_color} onChange={(e) => setKmk({ frame_color: e.target.value })} /></label>
              <label>Überschrift
                <select value={kmk.header_mode} onChange={(e) => setKmk({ header_mode: e.target.value })}>
                  <option value="first_field">im ersten Feld</option><option value="own_row">eigene Zeile</option><option value="hidden">ausblenden</option>
                </select>
              </label>
              <label className="check"><input type="checkbox" checked={kmk.seamless} onChange={(e) => setKmk({ seamless: e.target.checked })} />Gruppen lückenlos</label>
              <label className="check"><input type="checkbox" checked={kmk.include_reste} onChange={(e) => setKmk({ include_reste: e.target.checked })} />RESTE-Gruppe</label>
            </div>
          </section>
          <section className="card">
            <h3>Beschrifter-Inhalt (Zeilen auf dem Schild)</h3>
            <ul className="plain">
              {content.order.map((name) => (
                <li key={name}>
                  <input type="checkbox" checked={!!content.enabled[name]} onChange={(e) => setContent(content.order, { ...content.enabled, [name]: e.target.checked })} />
                  {name} <button onClick={() => moveContent(name, -1)}>↑</button><button onClick={() => moveContent(name, 1)}>↓</button>
                </li>
              ))}
            </ul>
          </section>
          <ColumnPanel config={config} update={update} />
        </div>

        <div>
          <section className="card">
            <div className="inline-form">
              <FormatChoice formats={formats} onChange={setFormats} />
              <label>Bereits beschriftete
                <select value={hideLabeled} onChange={(e) => setHideLabeled(e.target.value)} disabled={noLabelCols}>
                  <option value="">alle zeigen</option><option value="1">mit Ziel 1 beschriftet ausblenden</option>
                  <option value="2">mit Ziel 2 beschriftet ausblenden</option><option value="both">nur komplett beschriftete ausblenden</option>
                </select>
              </label>
              <button className="primary" disabled={toolApi.busy || !formats.length || !preview?.labels} onClick={() => void doExport()}>Exportieren</button>
            </div>
            <div className="inline-form">
              <span>Nach dem Export „beschriftet“ eintragen:</span>
              <select value={prefs.mode} onChange={(e) => setPrefs({ ...prefs, mode: e.target.value as Mode })}>
                <option value="ask">jedes Mal fragen</option><option value="auto">automatisch</option><option value="later">später entscheiden</option>
              </select>
              {prefs.mode === "auto" && (
                <select value={prefs.target} onChange={(e) => setPrefs({ ...prefs, target: e.target.value })}>
                  <option value="1">Ziel 1</option><option value="2">Ziel 2</option><option value="both">Ziel 1 + Ziel 2</option>
                </select>
              )}
            </div>
            {noLabelCols && <p className="muted">Die Spalten „beschriftet Ziel 1/2“ werden beim ersten Abhaken automatisch in der Liste angelegt.</p>}
            <Notice error={toolApi.error} />
            {message && <div className="banner">{message}</div>}
            {dialogRun && (
              <div className="banner warn dialog">
                <b>Export fertig ({dialogRun.count} Kabel).</b> Wurde schon gedruckt und beschriftet?
                <div className="inline-form">
                  <button className="primary" onClick={() => void mark(dialogRun, "1")}>Ziel 1</button>
                  <button className="primary" onClick={() => void mark(dialogRun, "2")}>Ziel 2</button>
                  <button className="primary" onClick={() => void mark(dialogRun, "both")}>Beide</button>
                  <button onClick={() => { setDialogRun(null); setMessage("Später entscheiden – siehe „Exportläufe“."); }}>Später entscheiden</button>
                </div>
              </div>
            )}
          </section>

          <section className="card">
            <h3>Vorschau {preview ? `(${preview.labels} Beschrifter)` : ""}</h3>
            {preview?.warnings.length ? <p className="warn">{preview.warnings.length} Beschrifter passen nicht in das Format.</p> : null}
            {preview?.groups.map((g) => (
              <div key={g.title} className="kmk-group">
                <h4>{g.title} <span className="chip">{g.count}</span></h4>
                <div className="kmk-labels">
                  {g.labels.map((l, i) => (
                    <div className="kmk-label" key={i} style={{ aspectRatio: `${kmk.kmk_type.width_mm} / ${kmk.kmk_type.height_mm}`, borderWidth: kmk.frame_enabled ? 1 : 0 }}>
                      {l.lines.map((line, k) => <div key={k}>{line}</div>)}
                    </div>
                  ))}
                </div>
              </div>
            ))}
            {preview && !preview.groups.length && <p className="muted">Keine Treffer – Suchbegriffe und Suchspalten prüfen.</p>}
          </section>

          <section className="card">
            <h3>Exportläufe</h3>
            <ul className="plain runs">
              {runs.map((run) => (
                <li key={run.id}>
                  <b>{new Date(run.created_at).toLocaleString("de-DE")}</b> · {run.created_by} · {run.count} Kabel · {run.formats.join("/")}<br />
                  <span className="muted">{status(run)}</span>
                  <span className="inline">
                    <button onClick={() => void mark(run, "1")}>Ziel 1 beschriftet</button>
                    <button onClick={() => void mark(run, "2")}>Ziel 2 beschriftet</button>
                    <button onClick={() => void mark(run, "both")}>Beide</button>
                    <button className="danger" onClick={() => void mark(run, "both", true)}>Zurücknehmen</button>
                  </span>
                </li>
              ))}
              {!runs.length && <li className="muted">Noch kein Export.</li>}
            </ul>
          </section>
        </div>
      </div>
    </div>
  );
}
