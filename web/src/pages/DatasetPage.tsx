import { useEffect, useMemo, useState } from "react";
import { Link, useParams, useSearchParams } from "react-router-dom";
import { api, download } from "../api";
import { useAuth } from "../auth";
import { CableView } from "../components/CableView";
import { DatasetState, getDb } from "../db";
import { datasetBackend } from "../sync";
import { CabinetTool } from "../tools/CabinetTool";
import { ConflictsTab } from "../tools/ConflictsTab";
import { HistoryTab } from "../tools/HistoryTab";
import { KmkTool } from "../tools/KmkTool";
import { OverviewTab } from "../tools/OverviewTab";
import { BatchTool, HighlightTool, SearchTool } from "../tools/SimpleTools";
import { TranslateTool } from "../tools/TranslateTool";
import type { ToolProps } from "../tools/types";

interface Share { id: number; label: string; mode: string; expires_at: string; revoked: boolean }

function SharePanel({ datasetId }: { datasetId: number }) {
  const [shares, setShares] = useState<Share[] | null>(null);
  const [label, setLabel] = useState("");
  const [mode, setMode] = useState("view");
  const [hours, setHours] = useState(72);
  const [created, setCreated] = useState("");
  const [error, setError] = useState("");

  const load = async () => {
    try {
      setShares(await api<Share[]>(`/api/datasets/${datasetId}/shares`));
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  };
  if (shares === null && !error) void load();

  const create = async () => {
    setError("");
    try {
      const r = await api<{ url: string }>(`/api/datasets/${datasetId}/shares`, { method: "POST", body: { label, mode, hours } });
      setCreated(r.url);
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  };

  return (
    <section className="card">
      <h3>Temporärer Link für Externe</h3>
      <div className="inline-form">
        <input placeholder="Bezeichnung (z. B. Kunde)" value={label} onChange={(e) => setLabel(e.target.value)} />
        <select value={mode} onChange={(e) => setMode(e.target.value)}>
          <option value="view">nur ansehen</option><option value="edit">Werte eintragen</option>
        </select>
        <label>gültig <input type="number" min={1} value={hours} className="narrow" onChange={(e) => setHours(Number(e.target.value))} /> Std.</label>
        <button className="primary" onClick={() => void create()}>Link erstellen</button>
      </div>
      {created && (
        <p className="ok">Link (wird nur jetzt angezeigt): <input readOnly value={created} onFocus={(e) => e.target.select()} className="wide" />
          <button onClick={() => void navigator.clipboard?.writeText(created)}>Kopieren</button></p>
      )}
      {error && <p className="error">{error}</p>}
      <ul className="plain">
        {shares?.map((s) => (
          <li key={s.id}>
            {s.label || `Link ${s.id}`} · {s.mode === "edit" ? "bearbeiten" : "ansehen"} · bis {new Date(s.expires_at).toLocaleString("de-DE")}
            {s.revoked ? <span className="chip">widerrufen</span> :
              <button className="danger" onClick={async () => { await api(`/api/datasets/${datasetId}/shares/${s.id}`, { method: "DELETE" }); await load(); }}>Widerrufen</button>}
          </li>
        ))}
      </ul>
    </section>
  );
}

const TABS = [
  { id: "cable", label: "Kabelzug" },
  { id: "search", label: "Einzelsuche" },
  { id: "batch", label: "Stapelsuche" },
  { id: "highlight", label: "Farbmarkierung" },
  { id: "kmk", label: "KMK" },
  { id: "cabinet", label: "Schrank-Erkennung" },
  { id: "translate", label: "Übersetzer" },
  { id: "overview", label: "Übersicht" },
  { id: "conflicts", label: "Konflikte" },
  { id: "history", label: "Verlauf" },
] as const;
type TabId = (typeof TABS)[number]["id"];

export function DatasetPage() {
  const { id } = useParams();
  const datasetId = Number(id);
  const [params, setParams] = useSearchParams();
  const { user } = useAuth();
  const backend = useMemo(() => datasetBackend(datasetId), [datasetId]);
  const [showShare, setShowShare] = useState(false);
  const [error, setError] = useState("");
  const [meta, setMeta] = useState<DatasetState | null>(null);
  const [conflicts, setConflicts] = useState(0);
  const [project, setProject] = useState<{ name: string } | null>(null);
  const requested = params.get("tab");
  const tab: TabId = TABS.some((t) => t.id === requested) ? (requested as TabId) : "cable";

  useEffect(() => {
    let alive = true;
    const refresh = async () => {
      const db = await getDb();
      const state = await db.get("datasets", backend.key);
      if (alive && state) setMeta(state);
      try {
        const list = await api<unknown[]>(`/api/datasets/${datasetId}/conflicts`);
        if (alive) setConflicts(list.length);
      } catch {
        /* offline: Zähler bleibt */
      }
    };
    void refresh();
    const fast = window.setInterval(() => void refresh(), 400); // bis die Liste zum ersten Mal geladen ist
    const timer = window.setInterval(() => void refresh(), 5000);
    const stopFast = window.setTimeout(() => window.clearInterval(fast), 15000);
    return () => { alive = false; window.clearInterval(timer); window.clearInterval(fast); window.clearTimeout(stopFast); };
  }, [backend.key, datasetId, tab]);

  useEffect(() => {
    if (!meta?.projectId) return;
    api<{ name: string }>(`/api/projects/${meta.projectId}`).then(setProject).catch(() => undefined);
  }, [meta?.projectId]);

  const props: ToolProps | null = meta
    ? { backend, datasetId, columns: meta.columns, creator: user?.display_name || user?.username || "", mapping: (meta.settings.mapping ?? {}) as Record<string, string | undefined>, settings: meta.settings as Record<string, unknown> }
    : null;

  return (
    <div>
      <p className="crumbs">
        <Link to="/">Projekte</Link>
        {meta?.projectId && <> / <Link to={`/projects/${meta.projectId}`}>{project?.name ?? "Projekt"}</Link></>}
        {meta && <> / <b>{meta.name}</b></>}
      </p>
      {error && <p className="error">{error}</p>}
      <nav className="tabs">
        {TABS.map((t) => (
          <button key={t.id} className={tab === t.id ? "active" : ""} onClick={() => setParams(t.id === "cable" ? {} : { tab: t.id })}>
            {t.label}{t.id === "conflicts" && conflicts > 0 && <span className="badge">{conflicts}</span>}
          </button>
        ))}
      </nav>
      {showShare && <SharePanel datasetId={datasetId} />}
      <div hidden={tab !== "cable"}>
        <CableView
          backend={backend}
          actions={
            <>
              <button onClick={() => download(`/api/datasets/${datasetId}/export`, `liste-${datasetId}.xlsx`).catch((e) => setError(String(e.message ?? e)))}>Excel-Export</button>
              <button onClick={() => setShowShare((v) => !v)}>Teilen</button>
            </>
          }
        />
      </div>
      {tab !== "cable" && !props && <p className="muted">Liste wird geladen …</p>}
      {props && tab === "search" && <SearchTool {...props} />}
      {props && tab === "batch" && <BatchTool {...props} />}
      {props && tab === "highlight" && <HighlightTool {...props} />}
      {props && tab === "kmk" && <KmkTool {...props} />}
      {props && tab === "cabinet" && <CabinetTool {...props} />}
      {props && tab === "translate" && <TranslateTool {...props} />}
      {props && tab === "overview" && <OverviewTab {...props} hasRoutes={!!(props.mapping.target1 || props.mapping.target2)} />}
      {props && tab === "history" && <HistoryTab backend={backend} datasetId={datasetId} />}
      {props && tab === "conflicts" && <ConflictsTab backend={backend} datasetId={datasetId} />}
    </div>
  );
}
