import { FormEvent, useCallback, useEffect, useMemo, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { api, errorText } from "../api";
import { addDays, deDay, deWhen, isoDay, parseDay, today, useProjects } from "../planning";

interface Ev {
  id: number; project_id: number | null; project: string; title: string; start: string; end: string;
  kind: string; color: string; note: string; done: boolean; created_by: string;
}
interface FeedEv { title: string; start: string; end: string; time: string; all_day: boolean }
interface Feed { id: number; project_id: number | null; project: string; name: string; color: string; error: string; fetched_at: string | null; events: FeedEv[] }
interface Calendar { events: Ev[]; feeds: Feed[] }
interface Item { key: string; title: string; start: string; end: string; color: string; time?: string; ev?: Ev; feed?: string; done?: boolean }

const KINDS: Record<string, string> = { phase: "Phase", termin: "Termin", urlaub: "Urlaub", meilenstein: "Meilenstein" };
const COLORS: [string, string][] = [["blue", "Blau"], ["green", "Grün"], ["red", "Rot"], ["orange", "Orange"], ["purple", "Violett"], ["gray", "Grau"]];
const WEEKDAYS = ["Mo", "Di", "Mi", "Do", "Fr", "Sa", "So"];

const mondayOf = (s: string) => { const d = parseDay(s); d.setDate(d.getDate() - ((d.getDay() + 6) % 7)); return isoDay(d); };
const monthTitle = (first: string) => parseDay(first).toLocaleDateString("de-DE", { month: "long", year: "numeric" });

/** Zeitplan/Kalender: eigene Phasen, Termine, Urlaub und Meilensteine plus externe Kalender (iCal-Link). */
export function SchedulePage() {
  const projects = useProjects();
  const [params, setParams] = useSearchParams();
  const scope = params.get("project") ?? "all";
  const [month, setMonth] = useState(() => today().slice(0, 7) + "-01");
  const [cal, setCal] = useState<Calendar | null>(null);
  const [agenda, setAgenda] = useState<Ev[]>([]);
  const [selected, setSelected] = useState<string>(today());
  const [form, setForm] = useState<Ev | "new" | null>(null);
  const [error, setError] = useState("");

  const gridStart = mondayOf(month);
  const gridEnd = addDays(gridStart, 41);
  const q = scope === "all" ? "" : `&project_id=${scope}`;
  const canWrite = scope === "all" || projects.find((p) => String(p.id) === scope)?.role !== "viewer";

  const load = useCallback(async () => {
    try {
      const [c, a] = await Promise.all([
        api<Calendar>(`/api/schedule?start=${gridStart}&end=${gridEnd}${q}`),
        api<Calendar>(`/api/schedule?start=${addDays(today(), -60)}&end=${addDays(today(), 400)}${q}`),
      ]);
      setCal(c);
      setAgenda(a.events.filter((e) => e.kind === "phase" || e.kind === "meilenstein"));
      setError("");
    } catch (e) { setError(errorText(e)); }
  }, [gridStart, gridEnd, q]);
  useEffect(() => void load(), [load]);

  const items = useMemo<Item[]>(() => {
    const own = (cal?.events ?? []).map((e) => ({ key: `e${e.id}`, title: e.title, start: e.start, end: e.end, color: e.color, ev: e, done: e.done }));
    const ext = (cal?.feeds ?? []).flatMap((f) => f.events.map((e, i) => ({
      key: `f${f.id}-${i}`, title: e.title, start: e.start, end: e.end, color: f.color, time: e.time, feed: f.name,
    })));
    return [...own, ...ext];
  }, [cal]);

  const days = useMemo(() => Array.from({ length: 42 }, (_, i) => addDays(gridStart, i)), [gridStart]);
  const on = (day: string) => items.filter((i) => i.start <= day && i.end >= day);
  const shift = (n: number) => { const d = parseDay(month); d.setMonth(d.getMonth() + n, 1); setMonth(isoDay(d)); };

  const toggleDone = async (e: Ev) => {
    try { await api(`/api/schedule/events/${e.id}`, { method: "PATCH", body: { done: !e.done } }); await load(); } catch (err) { setError(errorText(err)); }
  };

  return (
    <div className="schedule">
      <h1>Zeitplan &amp; Kalender</h1>
      <div className="search-row">
        <select value={scope} onChange={(e) => setParams(e.target.value === "all" ? {} : { project: e.target.value })} aria-label="Projekt">
          <option value="all">Alle Projekte</option>
          {projects.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}
        </select>
        <span className="segmented">
          <button onClick={() => shift(-1)} aria-label="Voriger Monat">‹</button>
          <button onClick={() => { setMonth(today().slice(0, 7) + "-01"); setSelected(today()); }}>Heute</button>
          <button onClick={() => shift(1)} aria-label="Nächster Monat">›</button>
        </span>
        <b className="month-title">{monthTitle(month)}</b>
        {canWrite && <button className="primary" onClick={() => setForm("new")}>Neuer Eintrag</button>}
      </div>
      {error && <p className="error">{error}</p>}

      <div className="cal-wrap">
        <div className="cal-grid" role="grid">
          {WEEKDAYS.map((d) => <div key={d} className="cal-head">{d}</div>)}
          {days.map((day) => {
            const list = on(day);
            const inMonth = day.slice(0, 7) === month.slice(0, 7);
            return (
              <div key={day} role="gridcell" tabIndex={0}
                   className={`cal-day${inMonth ? "" : " out"}${day === today() ? " today" : ""}${day === selected ? " sel" : ""}`}
                   onClick={() => setSelected(day)} onKeyDown={(e) => e.key === "Enter" && setSelected(day)}>
                <span className="cal-num">{Number(day.slice(8))}</span>
                {list.slice(0, 3).map((i) => (
                  <span key={i.key} className={`cal-ev c-${i.color}${i.done ? " done" : ""}${i.start === day ? " first" : ""}`} title={i.title}>{i.start === day || day === gridStart || parseDay(day).getDay() === 1 ? i.title : " "}</span>
                ))}
                {list.length > 3 && <span className="cal-more">+{list.length - 3}</span>}
              </div>
            );
          })}
        </div>

        <aside className="card cal-side">
          <h2>{deDay(selected)}</h2>
          {on(selected).length === 0 && <p className="muted">Nichts eingetragen.</p>}
          <ul className="plain">
            {on(selected).map((i) => (
              <li key={i.key} className="cal-item">
                <span className={`dot c-${i.color}`} />
                <div>
                  <b className={i.done ? "struck" : ""}>{i.title}</b>
                  <div className="muted small">
                    {i.ev ? `${KINDS[i.ev.kind] ?? i.ev.kind}${i.ev.project ? ` · ${i.ev.project}` : " · alle Projekte"}` : `Extern: ${i.feed}`}
                    {i.time && ` · ${i.time}`}{i.start !== i.end && ` · ${deDay(i.start)} – ${deDay(i.end)}`}
                  </div>
                  {i.ev?.note && <div className="muted small">{i.ev.note}</div>}
                  {i.ev && canWrite && <button onClick={() => setForm(i.ev!)}>Bearbeiten</button>}
                </div>
              </li>
            ))}
          </ul>
          {canWrite && <button onClick={() => setForm({ id: 0, project_id: scope === "all" ? null : Number(scope), project: "", title: "", start: selected, end: "", kind: "termin", color: "blue", note: "", done: false, created_by: "" })}>Eintrag für diesen Tag</button>}
        </aside>
      </div>

      {form && (
        <EventForm ev={form === "new" ? null : form} scope={scope} selected={selected} projects={projects}
                   onDone={() => { setForm(null); void load(); }} onCancel={() => setForm(null)} onError={setError} />
      )}

      <section className="card">
        <h2>Zeitplan: Phasen &amp; Meilensteine</h2>
        {agenda.length === 0 && <p className="muted">Noch keine Phasen. Mit „Neuer Eintrag“ → Art „Phase“ oder „Meilenstein“ den groben Ablauf anlegen.</p>}
        <ul className="plain timeline">
          {agenda.map((e) => (
            <li key={e.id} className={e.done ? "tl done" : e.end < today() ? "tl late" : "tl"}>
              <label className="check">
                <input type="checkbox" checked={e.done} disabled={!canWrite} onChange={() => void toggleDone(e)} />
                <span className={`dot c-${e.color}`} /> <b>{e.title}</b>
              </label>
              <span className="muted">{e.kind === "meilenstein" ? "Meilenstein" : "Phase"} · {deDay(e.start)}{e.end !== e.start && ` – ${deDay(e.end)}`}{e.project && ` · ${e.project}`}</span>
              {!e.done && e.end < today() && <span className="chip warn">überfällig</span>}
            </li>
          ))}
        </ul>
      </section>

      <Feeds cal={cal} scope={scope} canWrite={canWrite} projects={projects} onChanged={load} onError={setError} />
    </div>
  );
}

function EventForm({ ev, scope, selected, projects, onDone, onCancel, onError }: {
  ev: Ev | null; scope: string; selected: string; projects: { id: number; name: string; role: string }[];
  onDone: () => void; onCancel: () => void; onError: (e: string) => void;
}) {
  const fresh = ev === null || ev.id === 0;
  const [f, setF] = useState({
    title: ev?.title ?? "", start: ev?.start || selected, end: ev && ev.end !== ev.start ? ev.end : "", kind: ev?.kind ?? "phase",
    color: ev?.color ?? "blue", note: ev?.note ?? "",
    project: ev ? (ev.project_id ? String(ev.project_id) : "none") : scope === "all" ? "none" : scope,
  });
  const set = (k: keyof typeof f) => (e: { target: { value: string } }) => setF({ ...f, [k]: e.target.value });
  const submit = async (e: FormEvent) => {
    e.preventDefault();
    try {
      const body = { title: f.title, start: f.start, end: f.end, kind: f.kind, color: f.color, note: f.note };
      if (fresh) await api("/api/schedule/events", { method: "POST", body: { ...body, project_id: f.project === "none" ? null : Number(f.project) } });
      else await api(`/api/schedule/events/${ev!.id}`, { method: "PATCH", body });
      onError(""); onDone();
    } catch (err) { onError(errorText(err)); }
  };
  const remove = async () => {
    if (!ev || !confirm(`„${ev.title}“ löschen?`)) return;
    try { await api(`/api/schedule/events/${ev.id}`, { method: "DELETE" }); onDone(); } catch (err) { onError(errorText(err)); }
  };
  return (
    <form className="card" onSubmit={(e) => void submit(e)}>
      <h2>{fresh ? "Neuer Eintrag" : "Eintrag bearbeiten"}</h2>
      <div className="inline-form">
        <input className="wide" required placeholder="Titel, z. B. Rohbau Halle 2" value={f.title} onChange={set("title")} maxLength={200} />
        <select value={f.kind} onChange={set("kind")} aria-label="Art">{Object.entries(KINDS).map(([k, v]) => <option key={k} value={k}>{v}</option>)}</select>
        <select value={f.color} onChange={set("color")} aria-label="Farbe">{COLORS.map(([k, v]) => <option key={k} value={k}>{v}</option>)}</select>
      </div>
      <div className="inline-form">
        <label>von <input type="date" required value={f.start} onChange={set("start")} /></label>
        <label>bis <input type="date" value={f.end} min={f.start} onChange={set("end")} /></label>
        {fresh && (
          <select value={f.project} onChange={set("project")} aria-label="Projekt">
            <option value="none">Für alle Projekte</option>
            {projects.filter((p) => p.role !== "viewer").map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}
          </select>
        )}
      </div>
      <div className="inline-form">
        <input className="wide" placeholder="Notiz (optional)" value={f.note} onChange={set("note")} maxLength={500} />
        <button className="primary">Speichern</button><button type="button" onClick={onCancel}>Abbrechen</button>
        {!fresh && <button type="button" className="danger" onClick={() => void remove()}>Löschen</button>}
      </div>
    </form>
  );
}

function Feeds({ cal, scope, canWrite, projects, onChanged, onError }: {
  cal: Calendar | null; scope: string; canWrite: boolean; projects: { id: number; name: string; role: string }[];
  onChanged: () => Promise<void>; onError: (e: string) => void;
}) {
  const [name, setName] = useState("");
  const [url, setUrl] = useState("");
  const [color, setColor] = useState("gray");
  const [target, setTarget] = useState(scope === "all" ? "none" : scope);
  const [busy, setBusy] = useState(false);
  useEffect(() => setTarget(scope === "all" ? "none" : scope), [scope]);

  const run = async (fn: () => Promise<unknown>) => {
    setBusy(true);
    try { await fn(); onError(""); await onChanged(); } catch (e) { onError(errorText(e)); } finally { setBusy(false); }
  };
  const add = (e: FormEvent) => {
    e.preventDefault();
    void run(async () => {
      await api("/api/schedule/feeds", { method: "POST", body: { name, url, color, project_id: target === "none" ? null : Number(target) } });
      setName(""); setUrl("");
    });
  };

  return (
    <section className="card">
      <h2>Externe Kalender (Urlaub, Termine)</h2>
      <p className="muted">Füge den iCal-/ICS-Link eines Kalenders ein (Nextcloud, Google, Outlook: „Kalender teilen → Link / öffentliche Adresse im iCal-Format“). Die Termine erscheinen hier schreibgeschützt; der Server aktualisiert sie alle paar Stunden. Bei privaten Links nur die Adresse eintragen, die du auch weitergeben dürftest.</p>
      <ul className="plain">
        {cal?.feeds.map((f) => (
          <li key={f.id} className="feed-row">
            <span className={`dot c-${f.color}`} /> <b>{f.name}</b>
            <span className="muted">{f.project || "alle Projekte"} · {f.events.length} Termin(e) im sichtbaren Zeitraum{f.fetched_at && ` · Stand ${deWhen(f.fetched_at)}`}</span>
            {f.error && <span className="error">{f.error}</span>}
            {canWrite && (
              <span className="actions">
                <button disabled={busy} onClick={() => void run(() => api(`/api/schedule/feeds/${f.id}/refresh`, { method: "POST" }))}>Jetzt aktualisieren</button>
                <button className="danger" disabled={busy} onClick={() => confirm(`Kalender „${f.name}“ entfernen?`) && void run(() => api(`/api/schedule/feeds/${f.id}`, { method: "DELETE" }))}>Entfernen</button>
              </span>
            )}
          </li>
        ))}
        {cal?.feeds.length === 0 && <li className="muted">Noch kein externer Kalender verbunden.</li>}
      </ul>
      {canWrite && (
        <form className="inline-form" onSubmit={add}>
          <input required placeholder="Name, z. B. Urlaub Team" value={name} onChange={(e) => setName(e.target.value)} maxLength={200} />
          <input className="wide" required type="url" placeholder="https://…/calendar.ics" value={url} onChange={(e) => setUrl(e.target.value)} maxLength={1000} />
          <select value={color} onChange={(e) => setColor(e.target.value)} aria-label="Farbe">{COLORS.map(([k, v]) => <option key={k} value={k}>{v}</option>)}</select>
          <select value={target} onChange={(e) => setTarget(e.target.value)} aria-label="Gilt für">
            <option value="none">Für alle Projekte</option>
            {projects.filter((p) => p.role !== "viewer").map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}
          </select>
          <button className="primary" disabled={busy}>{busy ? "Prüfe Link …" : "Verbinden"}</button>
        </form>
      )}
    </section>
  );
}
