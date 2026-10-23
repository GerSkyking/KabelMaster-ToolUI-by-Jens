import { FormEvent, useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { OfflineError, api, errorText } from "../api";
import { kvGet, kvSet } from "../db";

export interface ProjectSummary {
  id: number;
  name: string;
  description: string;
  role: string;
  datasets: { id: number; name: string }[];
}

const ROLE: Record<string, string> = { owner: "Besitzer", editor: "Bearbeiten", viewer: "Lesen" };
const MAX_LISTS = 5;

export function ProjectsPage() {
  const [projects, setProjects] = useState<ProjectSummary[] | null>(null);
  const [cached, setCached] = useState(false);
  const [name, setName] = useState("");
  const [query, setQuery] = useState("");
  const [error, setError] = useState("");

  const load = async () => {
    try {
      const list = await api<ProjectSummary[]>("/api/projects");
      setProjects(list);
      setCached(false);
      void kvSet("projects", list);
    } catch (e) {
      if (e instanceof OfflineError) {
        setProjects((await kvGet<ProjectSummary[]>("projects")) ?? []);
        setCached(true);
      } else {
        setProjects([]);
        setError(errorText(e));
      }
    }
  };
  useEffect(() => void load(), []);

  const create = async (e: FormEvent) => {
    e.preventDefault();
    setError("");
    try {
      await api("/api/projects", { method: "POST", body: { name } });
      setName("");
      await load();
    } catch (err) {
      setError(errorText(err));
    }
  };

  const shown = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) return projects ?? [];
    return (projects ?? []).filter((p) =>
      `${p.name} ${p.description} ${p.datasets.map((d) => d.name).join(" ")}`.toLowerCase().includes(q));
  }, [projects, query]);

  return (
    <div>
      <h1>Projekte</h1>
      {cached && <p className="warn">Offline - zuletzt geladene Projektliste.</p>}
      {error && <p className="error">{error}</p>}
      {projects === null ? <p className="muted"><span className="spinner" /> Lade …</p> : (
        <>
          {projects.length > 4 && (
            <div className="search-row">
              <input type="search" placeholder="Projekt oder Liste suchen …" value={query} onChange={(e) => setQuery(e.target.value)} />
              <span className="muted">{shown.length} von {projects.length}</span>
            </div>
          )}
          <div className="cards">
            {shown.map((p) => (
              <div className="card" key={p.id}>
                <h3><Link to={`/projects/${p.id}`}>{p.name}</Link></h3>
                {p.description && <p className="muted">{p.description}</p>}
                <ul className="plain">
                  {p.datasets.slice(0, MAX_LISTS).map((d) => <li key={d.id}><Link to={`/datasets/${d.id}`}>{d.name}</Link></li>)}
                  {p.datasets.length > MAX_LISTS && <li className="muted"><Link to={`/projects/${p.id}#listen`}>… {p.datasets.length - MAX_LISTS} weitere</Link></li>}
                  {!p.datasets.length && <li className="muted">Noch keine Listen – im Projekt eine Excel-Datei hochladen.</li>}
                </ul>
                <div className="stat-line">
                  <span className="chip">{ROLE[p.role] ?? p.role}</span>
                  <span className="chip">{p.datasets.length} {p.datasets.length === 1 ? "Liste" : "Listen"}</span>
                </div>
              </div>
            ))}
          </div>
          {!projects.length && <p className="muted">Noch keine Projekte. Lege unten dein erstes Projekt an, lade dann eine Excel-Datei hoch und importiere sie als Liste.</p>}
          {!!projects.length && !shown.length && <p className="muted">Nichts gefunden.</p>}
        </>
      )}
      <form onSubmit={create} className="card inline-form">
        <input placeholder="Neues Projekt …" value={name} onChange={(e) => setName(e.target.value)} required maxLength={200} />
        <button className="primary">Projekt anlegen</button>
      </form>
    </div>
  );
}
