import { ChangeEvent, FormEvent, useCallback, useEffect, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { api, download, errorText, upload } from "../api";
import { Notes } from "../components/Notes";
import { datasetBackend, syncDataset } from "../sync";
import { ProjectOverview } from "./ProjectOverview";
import type { ProjectSummary } from "./ProjectsPage";

interface FileInfo { name: string; size: number; modified: number; imported: boolean }
interface UploadJob { name: string; loaded: number; total: number; state: "wait" | "run" | "done" | "error"; error?: string }
interface Member { user_id: number; username: string; display_name: string; role: string }

const size = (bytes: number) => (bytes > 1e6 ? `${(bytes / 1e6).toFixed(1)} MB` : `${Math.ceil(bytes / 1e3)} kB`);
const stamp = (seconds: number) => new Date(seconds * 1000).toLocaleString("de-DE", { dateStyle: "short", timeStyle: "short" });

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
  const [busy, setBusy] = useState("");
  const [jobs, setJobs] = useState<UploadJob[]>([]);
  const [dragging, setDragging] = useState(false);

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

  const patchJob = (index: number, change: Partial<UploadJob>) =>
    setJobs((list) => list.map((job, i) => (i === index ? { ...job, ...change } : job)));

  const uploadFiles = async (picked: File[]) => {
    if (!picked.length) return;
    setError("");
    setMessage("");
    setJobs(picked.map((f) => ({ name: f.name, loaded: 0, total: f.size, state: "wait" })));
    let ok = 0;
    for (const [index, file] of picked.entries()) {
      patchJob(index, { state: "run" });
      const form = new FormData();
      form.append("file", file);
      try {
        await upload(`/api/projects/${id}/files`, form, (loaded, total) => patchJob(index, { loaded, total }));
        patchJob(index, { state: "done", loaded: file.size });
        ok++;
        setFiles(await api<FileInfo[]>(`/api/projects/${id}/files`)); // Datei erscheint sofort in der Liste
      } catch (e) {
        patchJob(index, { state: "error", error: errorText(e) });
      }
    }
    if (ok) setMessage(ok === 1 ? "Datei hochgeladen." : `${ok} Dateien hochgeladen.`);
  };

  const onPick = (e: ChangeEvent<HTMLInputElement>) => {
    const picked = Array.from(e.target.files ?? []);
    e.target.value = "";
    void uploadFiles(picked);
  };

  const importFile = (name: string) => {
    setBusy(name);
    void run(async () => {
      try {
        const ds = await api<{ id: number }>(`/api/projects/${id}/datasets`, { method: "POST", body: { file: name } });
        navigate(`/datasets/${ds.id}`);
      } finally {
        setBusy("");
      }
    });
  };

  const deleteProject = async () => {
    if (!project) return;
    const ask = `Projekt „${project.name}“ mit ${project.datasets.length} Liste(n), allen Zeilen, Mitgliedern und Notizen löschen?\n\n` +
      "Das kann nicht rückgängig gemacht werden (eine Sicherung unter Verwaltung → Sicherungen schützt davor). " +
      "Die Dateien im Arbeitsverzeichnis bleiben auf dem Server liegen.";
    if (!confirm(ask)) return;
    setError("");
    try {
      await api(`/api/projects/${id}`, { method: "DELETE" });
      navigate("/");
    } catch (e) {
      setError(errorText(e));
    }
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

      <Notes projectId={Number(id)} canEdit={editor} />

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
                <td>{f.name}</td><td>{size(f.size)}</td><td className="muted">{stamp(f.modified)}</td>
                <td className="actions">
                  <button onClick={() => void download(`/api/projects/${id}/files/${encodeURIComponent(f.name)}`, f.name)}>Download</button>
                  {editor && /\.xlsx?$/i.test(f.name) && (
                    <button className="primary" disabled={busy !== ""} onClick={() => importFile(f.name)}>
                      {busy === f.name ? "Importiere …" : f.imported ? "Erneut importieren" : "Als Liste importieren"}
                    </button>
                  )}
                  {editor && <button className="danger" onClick={() => void run(() => api(`/api/projects/${id}/files/${encodeURIComponent(f.name)}`, { method: "DELETE" }))}>Löschen</button>}
                </td>
              </tr>
            ))}
            {!files.length && <tr><td className="muted">Keine Dateien</td></tr>}
          </tbody>
        </table>
        {busy && <p className="muted">Import läuft – bei großen Listen kann das einige Sekunden dauern. Bitte nicht schließen.</p>}
        {editor && (
          <div className={`dropzone${dragging ? " over" : ""}`}
               onDragOver={(e) => { e.preventDefault(); setDragging(true); }}
               onDragLeave={() => setDragging(false)}
               onDrop={(e) => { e.preventDefault(); setDragging(false); void uploadFiles(Array.from(e.dataTransfer.files)); }}>
            <label className="upload">Dateien hochladen oder hierher ziehen (.xlsx, .xls, .csv, .pdf)
              <input type="file" multiple accept=".xlsx,.xls,.csv,.pdf" onChange={onPick} />
            </label>
            {jobs.map((job, i) => {
              const pct = job.total ? Math.round((job.loaded / job.total) * 100) : 0;
              return (
                <div className="job" key={`${job.name}-${i}`}>
                  <span>{job.name}</span>
                  <progress max={100} value={job.state === "done" ? 100 : pct} />
                  <span className={job.state === "error" ? "error" : job.state === "done" ? "ok" : "muted"}>
                    {job.state === "wait" && "wartet"}
                    {job.state === "run" && (pct >= 100 ? "Server speichert …" : `${pct} % (${size(job.loaded)} von ${size(job.total)})`)}
                    {job.state === "done" && "fertig"}
                    {job.state === "error" && job.error}
                  </span>
                </div>
              );
            })}
          </div>
        )}
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

      {owner && (
        <section className="card danger-zone">
          <h2>Projekt löschen</h2>
          <p className="muted">Entfernt das Projekt mit allen Listen, Notizen und Mitgliedern aus der Datenbank.</p>
          <button className="danger" onClick={() => void deleteProject()}>Projekt löschen …</button>
        </section>
      )}
    </div>
  );
}
