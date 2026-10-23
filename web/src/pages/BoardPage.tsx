import { PointerEvent, useCallback, useEffect, useRef, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { api, errorText } from "../api";
import { useProjects } from "../planning";

interface Sticky {
  id: number; project_id: number | null; text: string; color: string; x: number; y: number; w: number; h: number;
  created_by: string; updated_by: string;
}
const COLORS = ["yellow", "green", "blue", "pink", "orange", "gray"];
const AREA = 2000;

/** Whiteboard aus Haftnotizen: je Projekt (/projects/:id/board) oder gemeinsam für alle (/board). */
export function BoardPage() {
  const { id } = useParams();
  const projectId = id ? Number(id) : null;
  const projects = useProjects();
  const navigate = useNavigate();
  const [notes, setNotes] = useState<Sticky[] | null>(null);
  const [error, setError] = useState("");
  const [color, setColor] = useState("yellow");
  const drag = useRef<{ id: number; dx: number; dy: number } | null>(null);
  const editing = useRef(false);
  const canvas = useRef<HTMLDivElement>(null);

  const role = projectId === null ? "editor" : projects.find((p) => p.id === projectId)?.role ?? "viewer";
  const canEdit = role !== "viewer";
  const query = projectId === null ? "" : `?project_id=${projectId}`;

  const load = useCallback(async () => {
    try {
      setNotes(await api<Sticky[]>(`/api/board${query}`));
      setError("");
    } catch (e) { setError(errorText(e)); }
  }, [query]);
  useEffect(() => { setNotes(null); void load(); }, [load]);
  useEffect(() => { // Änderungen der anderen übernehmen, aber nicht mitten im Ziehen oder Tippen
    const t = setInterval(() => { if (!drag.current && !editing.current && !document.hidden) void load(); }, 5000);
    return () => clearInterval(t);
  }, [load]);

  const patch = async (note: Sticky, body: Partial<Sticky>) => {
    try { await api(`/api/board/${note.id}`, { method: "PATCH", body }); } catch (e) { setError(errorText(e)); void load(); }
  };
  const update = (noteId: number, change: Partial<Sticky>) =>
    setNotes((list) => (list ?? []).map((n) => (n.id === noteId ? { ...n, ...change } : n)));

  const add = async () => {
    // neue Notiz in den sichtbaren Bereich legen, leicht versetzt, damit sie nicht genau übereinander liegen
    const box = canvas.current?.getBoundingClientRect();
    const scrollX = box ? Math.max(0, -box.left) : 0;
    const scrollY = box ? Math.max(0, -box.top + 120) : 0;
    const offset = ((notes?.length ?? 0) % 8) * 24;
    try {
      const created = await api<Sticky>("/api/board", { method: "POST", body: {
        project_id: projectId, color, text: "", x: Math.min(AREA - 220, 20 + scrollX + offset), y: Math.min(AREA - 160, 20 + scrollY + offset),
      } });
      setNotes((list) => [...(list ?? []), created]);
    } catch (e) { setError(errorText(e)); }
  };

  const remove = async (note: Sticky) => {
    if (note.text.trim() && !confirm("Notiz löschen?")) return;
    try { await api(`/api/board/${note.id}`, { method: "DELETE" }); setNotes((l) => (l ?? []).filter((n) => n.id !== note.id)); } catch (e) { setError(errorText(e)); }
  };

  const down = (note: Sticky) => (e: PointerEvent<HTMLDivElement>) => {
    if (!canEdit || (e.target as HTMLElement).closest("button")) return;
    (e.currentTarget as HTMLElement).setPointerCapture(e.pointerId);
    drag.current = { id: note.id, dx: e.clientX - note.x, dy: e.clientY - note.y };
  };
  const move = (note: Sticky) => (e: PointerEvent<HTMLDivElement>) => {
    const d = drag.current;
    if (!d || d.id !== note.id) return;
    update(note.id, {
      x: Math.round(Math.min(AREA - note.w, Math.max(0, e.clientX - d.dx))),
      y: Math.round(Math.min(AREA - note.h, Math.max(0, e.clientY - d.dy))),
    });
  };
  const up = (note: Sticky) => () => {
    if (drag.current?.id !== note.id) return;
    drag.current = null;
    const current = notes?.find((n) => n.id === note.id);
    if (current) void patch(current, { x: current.x, y: current.y });
  };

  const title = projectId === null ? "Gemeinsames Whiteboard" : `Whiteboard: ${projects.find((p) => p.id === projectId)?.name ?? "Projekt"}`;

  return (
    <div className="board-page">
      <h1>{title}</h1>
      <div className="search-row">
        <select value={projectId ?? "all"} onChange={(e) => navigate(e.target.value === "all" ? "/board" : `/projects/${e.target.value}/board`)} aria-label="Whiteboard wählen">
          <option value="all">Gemeinsam (alle Projekte, zur Planung)</option>
          {projects.map((p) => <option key={p.id} value={p.id}>Projekt: {p.name}</option>)}
        </select>
        {canEdit && (
          <>
            <span className="swatches" role="radiogroup" aria-label="Farbe">
              {COLORS.map((c) => <button key={c} type="button" className={`swatch sticky-${c}${color === c ? " on" : ""}`} aria-label={c} aria-checked={color === c} role="radio" onClick={() => setColor(c)} />)}
            </span>
            <button className="primary" onClick={() => void add()}>Neue Notiz</button>
          </>
        )}
        {!canEdit && <span className="muted">Nur Lesen</span>}
      </div>
      <p className="muted small">Notizen am Kopf ziehen, Text direkt eintippen – wird beim Verlassen des Feldes gespeichert. Änderungen anderer erscheinen nach wenigen Sekunden.</p>
      {error && <p className="error">{error}</p>}
      {notes === null && <p className="muted"><span className="spinner" /> Lade …</p>}
      <div className="board-scroll">
        <div className="board" ref={canvas} style={{ width: AREA, height: AREA }}>
          {notes?.length === 0 && <p className="muted board-empty">Noch leer. „Neue Notiz“ legt die erste an.</p>}
          {notes?.map((n) => (
            <div key={n.id} className={`sticky sticky-${n.color}`} style={{ left: n.x, top: n.y, width: n.w, height: n.h }}>
              <div className="sticky-head" onPointerDown={down(n)} onPointerMove={move(n)} onPointerUp={up(n)} onPointerCancel={up(n)}>
                <small>{n.updated_by || n.created_by}</small>
                {canEdit && (
                  <span>
                    <button type="button" aria-label="Farbe wechseln" title="Farbe wechseln"
                            onClick={() => { const c = COLORS[(COLORS.indexOf(n.color) + 1) % COLORS.length]; update(n.id, { color: c }); void patch(n, { color: c }); }}>◐</button>
                    <button type="button" aria-label="Notiz löschen" title="Löschen" onClick={() => void remove(n)}>✕</button>
                  </span>
                )}
              </div>
              <textarea value={n.text} readOnly={!canEdit} maxLength={4000} placeholder="Text …" aria-label="Notiztext"
                        onFocus={() => { editing.current = true; }}
                        onChange={(e) => update(n.id, { text: e.target.value })}
                        onBlur={() => { editing.current = false; void patch(n, { text: n.text }); }} />
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
