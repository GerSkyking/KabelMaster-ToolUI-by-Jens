// Übersicht: gezogene/fehlende Kabel je Querschnitt, Prognose, Tagesbericht, Konflikte.
import { useCallback, useEffect, useState } from "react";
import { api, errorText, fetchGet, saveBlob } from "../api";
import { syncDataset } from "../sync";
import type { ToolProps } from "./types";

export interface Section {
  label: string; total: number; done: number; open: number; percent: number; planned_m: number; done_m: number;
  predicted_open_m: number; forecast_m: number; delta_m: number; delta_percent: number;
  basis: { route: number; ratio: number; soll: number };
}
export interface DatasetOverview {
  id: number; name: string; ready: boolean; conflicts: number; sections?: Section[]; total?: Section;
  has_routes?: boolean; labeled?: { "1": number; "2": number; rows: number };
}

const fmt = (n: number, digits = 1) => n.toLocaleString("de-DE", { maximumFractionDigits: digits });
const signed = (n: number) => `${n > 0 ? "+" : ""}${fmt(n)}`;

export function OverviewTable({ overview }: { overview: DatasetOverview }) {
  if (!overview.ready || !overview.sections || !overview.total) {
    return <p className="muted">Für „{overview.name}“ fehlt die Spaltenzuordnung (Reiter Kabelzug → Spalten).</p>;
  }
  const rows = [...overview.sections, overview.total];
  return (
    <div className="table-wrap">
      <table className="analysis">
        <thead>
          <tr>
            <th>Querschnitt</th><th>Gezogen</th><th>Fehlt</th><th>Stand</th><th>Soll (m)</th><th>Gezogen (m)</th>
            <th>Prognose offen (m)</th><th>Prognose gesamt (m)</th><th>Abweichung</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((s, i) => (
            <tr key={s.label} className={i === rows.length - 1 ? "total" : ""}>
              <td>{s.label}</td>
              <td>{s.done} / {s.total}</td>
              <td>{s.open}</td>
              <td className="bar-cell"><div className="bar"><div style={{ width: `${s.percent}%` }} /></div>{fmt(s.percent)} %</td>
              <td>{fmt(s.planned_m)}</td>
              <td>{fmt(s.done_m)}</td>
              <td title={`Grundlage: ${s.basis.route} gleiche Strecke, ${s.basis.ratio} Verhältnis, ${s.basis.soll} Soll`}>{fmt(s.predicted_open_m)}</td>
              <td>{fmt(s.forecast_m)}</td>
              <td className={s.delta_m > 0 ? "warn" : ""}>{signed(s.delta_m)} m ({signed(s.delta_percent)} %)</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export function OverviewTab({ backend, datasetId, hasRoutes }: ToolProps & { hasRoutes: boolean }) {
  const [overview, setOverview] = useState<DatasetOverview | null>(null);
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");
  const [start, setStart] = useState("");
  const [end, setEnd] = useState("");

  const load = useCallback(async () => {
    setError("");
    try {
      await syncDataset(backend);
      setOverview(await api<DatasetOverview>(`/api/datasets/${datasetId}/overview`));
    } catch (e) {
      setError(errorText(e));
    }
  }, [backend, datasetId]);
  useEffect(() => void load(), [load]);

  const writeForecast = async () => {
    setMessage("");
    try {
      const r = await api<{ changed: number; column: string }>(`/api/datasets/${datasetId}/forecast/write`, { method: "POST", body: { only_empty: false } });
      setMessage(`${r.changed} Prognosewerte in die Spalte „${r.column}“ geschrieben.`);
      await syncDataset(backend);
      await load();
    } catch (e) {
      setError(errorText(e));
    }
  };
  const report = async () => {
    setError("");
    try {
      const query = new URLSearchParams({ ...(start ? { start } : {}), ...(end ? { end } : {}) }).toString();
      saveBlob(await fetchGet(`/api/datasets/${datasetId}/report.txt${query ? `?${query}` : ""}`, "Tagesbericht.txt"));
    } catch (e) {
      setError(errorText(e));
    }
  };

  return (
    <div className="tool">
      {error && <div className="banner error">{error}</div>}
      {message && <div className="banner">{message}</div>}
      <section className="card">
        <h3>Kabel je Querschnitt</h3>
        {overview ? <OverviewTable overview={overview} /> : <p className="muted">Lade …</p>}
        {!hasRoutes && <p className="muted">Hinweis: Ohne zugeordnete Spalten „Ziel 1/Ziel 2“ (Reiter Kabelzug → Spalten) nutzt die Prognose nur das Verhältnis Ist/Soll je Querschnitt.</p>}
        <p className="muted">Prognose: Kabel mit gleichem Querschnitt und gleichen Zielen sind gleich lang – Grundlage sind die ersten bis zu 3 gezogenen Kabel dieser Strecke.</p>
        {overview?.labeled && <p>Beschriftet: Ziel 1 {overview.labeled["1"] ?? 0} von {overview.labeled.rows}, Ziel 2 {overview.labeled["2"] ?? 0} von {overview.labeled.rows}</p>}
        <div className="inline-form">
          <button onClick={() => void load()}>Aktualisieren</button>
          <button onClick={() => void writeForecast()} disabled={!overview?.ready}>Prognose in Liste schreiben</button>
        </div>
      </section>
      <section className="card">
        <h3>Tagesbericht (TXT)</h3>
        <p className="muted">Pro Tag: gezogene Kabel und Meter, aufgeschlüsselt nach Querschnitt.</p>
        <div className="inline-form">
          <label>von<input type="date" value={start} onChange={(e) => setStart(e.target.value)} /></label>
          <label>bis<input type="date" value={end} onChange={(e) => setEnd(e.target.value)} /></label>
          <button className="primary" onClick={() => void report()} disabled={!overview?.ready}>Bericht herunterladen</button>
        </div>
      </section>
    </div>
  );
}
