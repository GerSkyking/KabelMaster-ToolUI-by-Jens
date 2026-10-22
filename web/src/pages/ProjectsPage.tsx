import { FormEvent, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { OfflineError, api } from "../api";
import { kvGet, kvSet } from "../db";

export interface ProjectSummary {
  id: number;
  name: string;
  description: string;
  role: string;
  datasets: { id: number; name: string }[];
}

export function ProjectsPage() {
  const [projects, setProjects] = useState<ProjectSummary[] | null>(null);
  const [cached, setCached] = useState(false);
  const [name, setName] = useState("");
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
      } else setError(e instanceof Error ? e.message : String(e));
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
      setError(err instanceof Error ? err.message : String(err));
    }
  };

  return (
    <div>
      <h1>Projekte</h1>
      {cached && <p className="warn">Offline - zuletzt geladene Projektliste.</p>}
      {error && <p className="error">{error}</p>}
      {projects === null ? <p className="muted">Lade …</p> : (
        <div className="cards">
          {projects.map((p) => (
            <div className="card" key={p.id}>
              <h3><Link to={`/projects/${p.id}`}>{p.name}</Link></h3>
              {p.description && <p className="muted">{p.description}</p>}
              <ul className="plain">
                {p.datasets.map((d) => <li key={d.id}><Link to={`/datasets/${d.id}`}>{d.name}</Link></li>)}
                {!p.datasets.length && <li className="muted">Noch keine Listen</li>}
              </ul>
              <span className="chip">{p.role}</span>
            </div>
          ))}
          {!projects.length && <p className="muted">Noch keine Projekte.</p>}
        </div>
      )}
      <form onSubmit={create} className="card inline-form">
        <input placeholder="Neues Projekt …" value={name} onChange={(e) => setName(e.target.value)} required />
        <button className="primary">Projekt anlegen</button>
      </form>
    </div>
  );
}
