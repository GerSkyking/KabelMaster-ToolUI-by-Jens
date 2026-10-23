import { useCallback, useEffect, useMemo, useState } from "react";
import { api, errorText } from "../api";
import { renderMarkdown, toggleTask } from "../markdown";

interface NoteInfo { id: number; title: string; preview?: string; updated_by: string; updated_at: string }
interface NoteFull extends NoteInfo { body: string; version: number }
interface Draft { id: number | null; title: string; body: string; version: number | null }

const when = (iso: string) => new Date(iso).toLocaleString("de-DE", { dateStyle: "short", timeStyle: "short" });

/** Notizen eines Projekts (Markdown). Nur Bearbeiter dürfen schreiben; gespeichert wird mit Versionsprüfung. */
export function Notes({ projectId, canEdit }: { projectId: number; canEdit: boolean }) {
  const base = `/api/projects/${projectId}/notes`;
  const [notes, setNotes] = useState<NoteInfo[] | null>(null);
  const [draft, setDraft] = useState<Draft | null>(null);
  const [saved, setSaved] = useState<Draft | null>(null);
  const [editing, setEditing] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  const refresh = useCallback(async () => {
    try {
      setNotes(await api<NoteInfo[]>(base));
    } catch (e) {
      setError(errorText(e));
    }
  }, [base]);
  useEffect(() => void refresh(), [refresh]);

  const dirty = draft !== null && saved !== null && (draft.title !== saved.title || draft.body !== saved.body);
  const html = useMemo(() => renderMarkdown(draft?.body ?? ""), [draft?.body]);
  const discardOk = () => !dirty || confirm("Ungespeicherte Änderungen verwerfen?");

  const open = async (id: number) => {
    if (!discardOk()) return;
    setError("");
    try {
      const note = await api<NoteFull>(`${base}/${id}`);
      const next = { id: note.id, title: note.title, body: note.body, version: note.version };
      setDraft(next);
      setSaved(next);
      setEditing(false);
    } catch (e) {
      setError(errorText(e));
    }
  };

  const create = () => {
    if (!discardOk()) return;
    const next: Draft = { id: null, title: "", body: "", version: null };
    setDraft(next);
    setSaved(next);
    setEditing(true);
  };

  const save = async (current: Draft | null = draft) => {
    if (!current) return;
    setBusy(true);
    setError("");
    try {
      const payload = { title: current.title, body: current.body, version: current.version };
      const note = current.id === null
        ? await api<NoteFull>(base, { method: "POST", body: payload })
        : await api<NoteFull>(`${base}/${current.id}`, { method: "PUT", body: payload });
      const next = { id: note.id, title: note.title === "Ohne Titel" ? "" : note.title, body: note.body, version: note.version };
      setDraft(next);
      setSaved(next);
      await refresh();
    } catch (e) {
      setError(errorText(e));
    } finally {
      setBusy(false);
    }
  };

  // Häkchen in der Vorschau anklicken: im Lesemodus sofort speichern, im Bearbeiten-Modus nur den Text ändern
  const onPreviewClick = (e: React.MouseEvent) => {
    const item = (e.target as HTMLElement).closest("li.task[data-line]");
    if (!item || !canEdit || !draft || busy) return;
    const next = { ...draft, body: toggleTask(draft.body, Number(item.getAttribute("data-line"))) };
    setDraft(next);
    if (!editing && next.id !== null) void save(next);
  };

  const remove = async () => {
    if (!draft || draft.id === null || !confirm("Notiz endgültig löschen?")) return;
    setError("");
    try {
      await api(`${base}/${draft.id}`, { method: "DELETE" });
      setDraft(null);
      setSaved(null);
      await refresh();
    } catch (e) {
      setError(errorText(e));
    }
  };

  const onKey = (e: React.KeyboardEvent) => {
    if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "s") {
      e.preventDefault();
      if (dirty && !busy) void save();
    }
  };

  return (
    <section className="card notes">
      <div className="inline">
        <h2>Notizen</h2>
        {canEdit && <button onClick={create}>Neue Notiz</button>}
      </div>
      {error && <p className="error">{error}</p>}
      <div className="notes-layout">
        <ul className="plain note-list">
          {notes === null && <li className="muted">Lade …</li>}
          {notes?.map((n) => (
            <li key={n.id}>
              <button className={`note-item${draft?.id === n.id ? " active" : ""}`} onClick={() => void open(n.id)}>
                <b>{n.title}</b>
                <span className="muted">{when(n.updated_at)} · {n.updated_by}</span>
                {n.preview && <span className="muted note-preview">{n.preview}</span>}
              </button>
            </li>
          ))}
          {notes?.length === 0 && <li className="muted">Noch keine Notizen.</li>}
        </ul>

        {draft ? (
          <div className="note-editor" onKeyDown={onKey}>
            {editing && canEdit ? (
              <input className="wide" placeholder="Titel" value={draft.title}
                     onChange={(e) => setDraft({ ...draft, title: e.target.value })} />
            ) : (
              <h3>{draft.title || "Ohne Titel"}</h3>
            )}
            <div className={editing && canEdit ? "note-split" : ""}>
              {editing && canEdit && (
                <textarea value={draft.body} rows={16} spellCheck
                          placeholder={"# Überschrift\n- Liste\n- [ ] Aufgabe\n\n**fett**, *kursiv*, `code`, [Link](https://…)"}
                          onChange={(e) => setDraft({ ...draft, body: e.target.value })} />
              )}
              <div className={`markdown${canEdit ? " editable" : ""}`} onClick={onPreviewClick} dangerouslySetInnerHTML={{ __html: html || "<p class='muted'>Leer.</p>" }} />
            </div>
            <div className="inline">
              {canEdit && !editing && <button onClick={() => setEditing(true)}>Bearbeiten</button>}
              {canEdit && editing && (
                <>
                  <button className="primary" disabled={busy || (!dirty && draft.id !== null)} onClick={() => void save()}>
                    {busy ? "Speichere …" : "Speichern"}
                  </button>
                  {draft.id !== null && <button onClick={() => setEditing(false)}>Nur Ansicht</button>}
                </>
              )}
              {canEdit && draft.id !== null && <button className="danger" onClick={() => void remove()}>Löschen</button>}
              {dirty && <span className="warn">Nicht gespeichert</span>}
            </div>
          </div>
        ) : (
          <p className="muted">Notiz wählen oder neu anlegen. Format: Markdown (Überschriften, Listen, Aufgaben, Tabellen, Code).</p>
        )}
      </div>
    </section>
  );
}
