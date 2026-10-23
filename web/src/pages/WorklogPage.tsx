import { FormEvent, useCallback, useEffect, useMemo, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { api, download, errorText } from "../api";
import { PERIOD_LABEL, deDay, num, qtyText, today, useProjects, useStored } from "../planning";

interface Entry { id: number; project_id: number; project: string; day: string; text: string; hours: number | null }
interface Period { period: string; entries: number; hours: number; days: number; edits: number }
type Group = "day" | "week" | "month" | "year";
const GROUPS: [Group, string][] = [["day", "Tag"], ["week", "Woche"], ["month", "Monat"], ["year", "Jahr"]];
const weekday = (s: string) => new Date(`${s}T00:00:00`).toLocaleDateString("de-DE", { weekday: "long" });

/** Persönlicher Tagesbericht: was habe ich im Projekt gemacht? Nur für mich sichtbar, mit Auswertung. */
export function WorklogPage() {
  const projects = useProjects();
  const [params, setParams] = useSearchParams();
  const scope = params.get("project") ?? "all";
  const [group, setGroup] = useStored<Group>("worklog.group", "week");
  const [entries, setEntries] = useState<Entry[] | null>(null);
  const [periods, setPeriods] = useState<Period[]>([]);
  const [from, setFrom] = useState("");
  const [to, setTo] = useState("");
  const [error, setError] = useState("");

  const [day, setDay] = useState(today());
  const [text, setText] = useState("");
  const [hours, setHours] = useState("");
  const [target, setTarget] = useState("");

  const filter = useMemo(() => {
    const p = new URLSearchParams();
    if (scope !== "all") p.set("project_id", scope);
    if (from) p.set("date_from", from);
    if (to) p.set("date_to", to);
    return p;
  }, [scope, from, to]);

  const load = useCallback(async () => {
    try {
      const [list, sum] = await Promise.all([
        api<Entry[]>(`/api/worklog?${filter}`),
        api<Period[]>(`/api/worklog/summary?${filter}&group=${group}`),
      ]);
      setEntries(list); setPeriods(sum); setError("");
    } catch (e) { setError(errorText(e)); }
  }, [filter, group]);
  useEffect(() => void load(), [load]);
  useEffect(() => { if (!target && projects.length) setTarget(scope !== "all" ? scope : String(projects[0].id)); }, [projects, scope, target]);
  useEffect(() => { if (scope !== "all") setTarget(scope); }, [scope]);

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    const h = hours.trim() ? num(hours) : null;
    if (h !== null && !(h >= 0 && h <= 24)) { setError("Stunden zwischen 0 und 24 angeben."); return; }
    try {
      await api("/api/worklog", { method: "POST", body: { project_id: Number(target), day, text, hours: h } });
      setText(""); setHours("");
      await load();
    } catch (err) { setError(errorText(err)); }
  };
  const edit = async (entry: Entry) => {
    const next = prompt("Tätigkeit ändern", entry.text);
    if (next === null || !next.trim()) return;
    try { await api(`/api/worklog/${entry.id}`, { method: "PATCH", body: { text: next } }); await load(); } catch (e) { setError(errorText(e)); }
  };
  const remove = async (entry: Entry) => {
    if (!confirm("Eintrag löschen?")) return;
    try { await api(`/api/worklog/${entry.id}`, { method: "DELETE" }); await load(); } catch (e) { setError(errorText(e)); }
  };

  const byDay = useMemo(() => {
    const map = new Map<string, Entry[]>();
    for (const e of entries ?? []) map.set(e.day, [...(map.get(e.day) ?? []), e]);
    return [...map.entries()];
  }, [entries]);
  const totalHours = (entries ?? []).reduce((s, e) => s + (e.hours ?? 0), 0);

  return (
    <div className="worklog">
      <h1>Tagesbericht</h1>
      <p className="muted">Nur für dich sichtbar: was hast du heute im Projekt geschafft? Daraus entsteht deine Auswertung nach Tag, Woche, Monat und Jahr. Deine Änderungen in den Listen werden automatisch mitgezählt.</p>

      <form className="card" onSubmit={(e) => void submit(e)}>
        <h2>Eintrag hinzufügen</h2>
        <div className="inline-form">
          <select value={target} onChange={(e) => setTarget(e.target.value)} required aria-label="Projekt">
            {projects.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}
          </select>
          <input type="date" value={day} max={today()} onChange={(e) => setDay(e.target.value)} required aria-label="Tag" />
          <input className="narrow" inputMode="decimal" placeholder="Std." value={hours} onChange={(e) => setHours(e.target.value)} aria-label="Stunden" title="Stunden (optional)" />
        </div>
        <div className="inline-form">
          <textarea rows={2} required maxLength={5000} placeholder="Was wurde gemacht? z. B. Kabel W-120 bis W-180 gezogen, Schrank 3 beschriftet" value={text} onChange={(e) => setText(e.target.value)} />
          <button className="primary" disabled={!target}>Speichern</button>
        </div>
      </form>

      <div className="search-row">
        <select value={scope} onChange={(e) => setParams(e.target.value === "all" ? {} : { project: e.target.value })} aria-label="Projekt filtern">
          <option value="all">Alle Projekte</option>
          {projects.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}
        </select>
        <label>von <input type="date" value={from} onChange={(e) => setFrom(e.target.value)} /></label>
        <label>bis <input type="date" value={to} onChange={(e) => setTo(e.target.value)} /></label>
        <button onClick={() => void download(`/api/worklog/export?${filter}`, "tagesbericht.xlsx").catch((e) => setError(errorText(e)))}>Excel-Export</button>
      </div>
      {error && <p className="error">{error}</p>}

      <section className="card">
        <div className="inline">
          <h2>Auswertung</h2>
          <span className="segmented">
            {GROUPS.map(([id, label]) => <button key={id} className={group === id ? "active" : ""} onClick={() => setGroup(id)}>{label}</button>)}
          </span>
        </div>
        {periods.length === 0 ? <p className="muted">Noch keine Daten im gewählten Bereich.</p> : (
          <div className="table-wrap">
            <table className="analysis">
              <thead><tr><th>Zeitraum</th><th>Arbeitstage</th><th>Einträge</th><th>Stunden</th><th>Änderungen in Listen</th></tr></thead>
              <tbody>
                {periods.map((p) => (
                  <tr key={p.period}><td>{PERIOD_LABEL(p.period)}</td><td>{p.days}</td><td>{p.entries}</td><td>{p.hours ? qtyText(p.hours) : "–"}</td><td>{p.edits || "–"}</td></tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>

      <section className="card">
        <h2>Einträge {entries && <small className="muted">({entries.length}{totalHours ? `, ${qtyText(totalHours)} Std.` : ""})</small>}</h2>
        {entries === null && <p className="muted"><span className="spinner" /> Lade …</p>}
        {entries?.length === 0 && <p className="muted">Noch keine Einträge. Oben den ersten anlegen.</p>}
        {byDay.map(([d, list]) => (
          <div key={d} className="log-day">
            <h3>{weekday(d)}, {deDay(d)}</h3>
            <ul className="plain">
              {list.map((e) => (
                <li key={e.id} className="log-entry">
                  <div>
                    <span className="chip">{e.project}</span>{e.hours != null && <span className="chip">{qtyText(e.hours)} Std.</span>}
                    <div className="log-text">{e.text}</div>
                  </div>
                  <span className="actions"><button onClick={() => void edit(e)}>Bearbeiten</button><button className="danger" onClick={() => void remove(e)}>Löschen</button></span>
                </li>
              ))}
            </ul>
          </div>
        ))}
      </section>
    </div>
  );
}
