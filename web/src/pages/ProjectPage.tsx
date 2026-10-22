import { ChangeEvent, FormEvent, useCallback, useEffect, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { api, download } from "../api";
import { datasetBackend, syncDataset } from "../sync";
import { ProjectOverview } from "./ProjectOverview";
import type { ProjectSummary } from "./ProjectsPage";

interface FileInfo { name: string; size: number; imported: boolean }
interface Member { user_id: number; username: string; display_name: string; role: string }

const size = (bytes: number) => (bytes > 1e6 ? `${(bytes / 1e6).toFixed(1)} MB` : `${Math.ceil(bytes / 1e3)} kB`);

export function ProjectPage() {
  const { id } = useParams();
  const navigate = useNavigate();
  const [project, setProject] = useState<ProjectSummary | null>(null);
  const [files, setFiles] = useState<FileInfo[]>([]);
  const [members, setMembers] = useState<Member[]>([]);
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");
  const [memberName, setMemberName] = useState("");
  const [memberRole, setMemberRole] = useState("editor");

  const load = useCallback(async () => {
    try {
      setProject(await api<ProjectSummary>(`/api/projects/${id}`));
      setFiles(await api<FileInfo[]>(`/api/projects/${id}/files`));
      setMembers(await api<Member[]>(`/api/projects/${id}/members`));
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  }, [id]);
  useEffect(() => void load(), [load]);

  const run = async (action: () => Promise<unknown>, done = "") => {
    setError("");
    setMessage("");
    try {
      await action();
      if (done) setMessage(done);
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  };

  const upload = (e: ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    e.target.value = "";
    if (!file) return;
    const form = new FormData();
    form.append("file", file);
    void run(() => api(`/api/projects/${id}/files`, { method: "POST", form }), `${file.name} hochgeladen.`);
  };

  const addMember = (e: FormEvent) => {
    e.preventDefault();
    void run(async () => {
      await api(`/api/projects/${id}/members`, { method: "PUT", body: { username: memberName, role: memberRole } });
      setMemberName("");
    });
  };

  if (!project) return <p className="muted">{error || "Lade …"}</p>;
  const owner = project.role === "owner";
  const editor = owner || project.role === "editor";

  return (
    <div>
      <h1>{project.name}</h1>
      {project.description && <p className="muted">{project.description}</p>}
      {message && <p className="ok">{message}</p>}
      {error && <p className="error">{error}</p>}

      <ProjectOverview projectId={Number(id)} canEdit={editor} />

      <section className="card">
        <h2>Listen</h2>
        <ul className="plain">
          {project.datasets.map((d) => (
            <li key={d.id}>
              <Link to={`/datasets/${d.id}`}>{d.name}</Link>{" "}
              <button onClick={() => void run(() => syncDataset(datasetBackend(d.id)), `${d.name} für Offline-Nutzung geladen.`)}>Offline bereithalten</button>
              {owner && <button className="danger" onClick={() => confirm(`Liste „${d.name}“ löschen?`) && void run(() => api(`/api/datasets/${d.id}`, { method: "DELETE" }))}>Löschen</button>}
            </li>
          ))}
          {!project.datasets.length && <li className="muted">Noch keine Liste - Excel-Datei hochladen und importieren.</li>}
        </ul>
      </section>

      <section className="card">
        <h2>Arbeitsverzeichnis (Dateien)</h2>
        <table className="data">
          <tbody>
            {files.map((f) => (
              <tr key={f.name}>
                <td>{f.name}</td><td>{size(f.size)}</td>
                <td className="actions">
                  <button onClick={() => void download(`/api/projects/${id}/files/${encodeURIComponent(f.name)}`, f.name)}>Download</button>
                  {editor && /\.xlsx?$/i.test(f.name) && (
                    <button className="primary" onClick={() => void run(async () => {
                      const ds = await api<{ id: number }>(`/api/projects/${id}/datasets`, { method: "POST", body: { file: f.name } });
                      navigate(`/datasets/${ds.id}`);
                    })}>{f.imported ? "Erneut importieren" : "Als Liste importieren"}</button>
                  )}
                  {editor && <button className="danger" onClick={() => void run(() => api(`/api/projects/${id}/files/${encodeURIComponent(f.name)}`, { method: "DELETE" }))}>Löschen</button>}
                </td>
              </tr>
            ))}
            {!files.length && <tr><td className="muted">Keine Dateien</td></tr>}
          </tbody>
        </table>
        {editor && <label className="upload">Datei hochladen (.xlsx, .xls, .csv, .pdf)<input type="file" accept=".xlsx,.xls,.csv,.pdf" onChange={upload} /></label>}
      </section>

      <section className="card">
        <h2>Mitglieder</h2>
        <ul className="plain">
          {members.map((m) => (
            <li key={m.user_id}>
              {m.display_name || m.username} <span className="chip">{m.role}</span>
              {owner && <button className="danger" onClick={() => void run(() => api(`/api/projects/${id}/members/${m.user_id}`, { method: "DELETE" }))}>Entfernen</button>}
            </li>
          ))}
        </ul>
        {owner && (
          <form onSubmit={addMember} className="inline-form">
            <input placeholder="Benutzername" value={memberName} onChange={(e) => setMemberName(e.target.value)} required />
            <select value={memberRole} onChange={(e) => setMemberRole(e.target.value)}>
              <option value="viewer">Lesen</option><option value="editor">Bearbeiten</option><option value="owner">Besitzer</option>
            </select>
            <button>Hinzufügen</button>
          </form>
        )}
      </section>
    </div>
  );
}
