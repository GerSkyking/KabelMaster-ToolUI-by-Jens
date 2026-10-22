import { ReactNode, useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  Mapping, MAPPING_FIELDS, analyze, computeLength, display, excelLetter, formatNumber, mappingComplete,
  parseNumber, percent, rowState, shortDate, RowState,
} from "../cable";
import type { LocalRow } from "../db";
import { Backend } from "../sync";
import { useDataset } from "../useDataset";

const RENDER_LIMIT = 300;
type Filter = "all" | "open" | "done";

function toCell(text: string): string | number | null {
  const t = text.trim();
  if (!t) return null;
  return /^-?\d+([.,]\d+)?$/.test(t) ? Number(t.replace(",", ".")) : t;
}

const STATE_LABEL: Record<RowState, string> = { open: "offen", done: "gezogen", ignored: "kurzes Ende" };

export function CableView({ backend, actions }: { backend: Backend; actions?: ReactNode }) {
  const ds = useDataset(backend);
  const { state, rows } = ds;
  const columns = state?.columns ?? [];
  const mapping: Mapping = state?.settings.mapping ?? {};
  const opts = { ignoreShort: !!state?.settings.ignore_short, minLength: state?.settings.min_length ?? 2 };
  const autoDate = !!state?.settings.auto_date;
  const canEdit = !!state?.canEdit;
  const complete = mappingComplete(mapping, columns);

  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [filter, setFilter] = useState<Filter>("all");
  const [query, setQuery] = useState("");
  const [showSettings, setShowSettings] = useState(false);
  const [showAnalysis, setShowAnalysis] = useState(false);
  const [limit, setLimit] = useState(RENDER_LIMIT);
  const [startText, setStartText] = useState("");
  const [endText, setEndText] = useState("");
  const [dateText, setDateText] = useState("");
  const dirty = useRef(false);
  const startRef = useRef<HTMLInputElement>(null);
  const endRef = useRef<HTMLInputElement>(null);
  const dateRef = useRef<HTMLInputElement>(null);

  const analysis = useMemo(() => (complete ? analyze(rows.map((r) => r.data), mapping, opts) : null),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [rows, state?.settings, complete]);

  const visible = useMemo(() => {
    const q = query.trim().toLowerCase();
    return rows.filter((r) => {
      if (complete && filter !== "all") {
        const s = rowState(r.data, mapping, opts);
        if (filter === "open" && s !== "open") return false;
        if (filter === "done" && s !== "done") return false;
      }
      return !q || Object.values(r.data).some((v) => display(v).toLowerCase().includes(q));
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [rows, filter, query, state?.settings, complete]);

  const selected = rows.find((r) => r.id === selectedId) ?? null;

  // Ohne vollständige Zuordnung die Einstellungen von selbst öffnen; danach bleiben sie, bis man sie schließt
  useEffect(() => {
    if (state && !complete && canEdit && !backend.share) setShowSettings(true);
  }, [state, complete, canEdit, backend.share]);

  // Eingabefelder mit dem gewählten Kabel füllen (nicht überschreiben, solange gerade getippt wird)
  const loadForm = useCallback((row: LocalRow | null) => {
    setStartText(row && mapping.start ? display(row.data[mapping.start]) : "");
    setEndText(row && mapping.end ? display(row.data[mapping.end]) : "");
    setDateText(row && mapping.date ? display(row.data[mapping.date]) : "");
    dirty.current = false;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [mapping.start, mapping.end, mapping.date]);

  useEffect(() => loadForm(selected), [selectedId]); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => {
    if (!dirty.current) loadForm(selected);
  }, [selected, loadForm]);
  useEffect(() => {
    if (selectedId === null && rows.length) setSelectedId(rows[0].id);
  }, [rows, selectedId]);

  const commit = useCallback(async () => {
    if (!selected || !canEdit || !complete || !dirty.current) return;
    const start = mapping.start!, end = mapping.end!, pulled = mapping.pulled_length!;
    const length = computeLength(startText, endText);
    const wasDone = (parseNumber(selected.data[pulled]) ?? 0) > 0;
    let date = dateText;
    if (autoDate && mapping.date && !wasDone && (length ?? 0) > 0 && !date.trim()) {
      date = shortDate();
      setDateText(date);
    }
    const next: Record<string, unknown> = { [start]: toCell(startText), [end]: toCell(endText), [pulled]: length };
    if (mapping.date) next[mapping.date] = date.trim() || null;
    const patch = Object.fromEntries(
      Object.entries(next).filter(([k, v]) => display(v) !== display(selected.data[k])),
    );
    dirty.current = false;
    if (Object.keys(patch).length) await ds.edit(selected.id, patch);
  }, [selected, canEdit, complete, mapping, startText, endText, dateText, autoDate, ds]);

  const select = useCallback(async (id: number) => {
    await commit();
    setSelectedId(id);
    setTimeout(() => document.getElementById(`row-${id}`)?.scrollIntoView({ block: "nearest" }), 0);
  }, [commit]);

  const step = useCallback((delta: number) => {
    if (!visible.length) return;
    const index = visible.findIndex((r) => r.id === selectedId);
    const target = visible[Math.min(Math.max((index < 0 ? 0 : index) + delta, 0), visible.length - 1)];
    if (target) void select(target.id);
  }, [visible, selectedId, select]);

  const finish = useCallback(async () => {
    await commit();
    const index = visible.findIndex((r) => r.id === selectedId);
    const next =
      visible.slice(index + 1).find((r) => complete && rowState(r.data, mapping, opts) === "open") ?? visible[index + 1];
    if (next) setSelectedId(next.id);
    setTimeout(() => {
      if (next) document.getElementById(`row-${next.id}`)?.scrollIntoView({ block: "nearest" });
      startRef.current?.focus();
      startRef.current?.select();
    }, 0);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [commit, visible, selectedId, complete, state?.settings]);

  // Pfeiltasten wählen das Kabel - auch aus den Eingabefeldern heraus
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const target = e.target as HTMLElement;
      if (["SELECT", "TEXTAREA"].includes(target.tagName) || target.id === "search" || target.dataset.skipNav === "1") return;
      const delta = { ArrowUp: -1, ArrowDown: 1, PageUp: -10, PageDown: 10 }[e.key];
      if (delta) {
        e.preventDefault();
        step(delta);
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [step]);

  const length = computeLength(startText, endText);
  const total = analysis?.total;
  const pct = total ? percent(total.done, total.total) : 0;

  const setMapping = async (key: keyof Mapping, value: string) => {
    let column = value;
    if (value === "__new__") {
      const base = MAPPING_FIELDS.find((f) => f.key === key)!.newName;
      let name = base, n = 2;
      while (columns.includes(name)) name = `${base} (${n++})`;
      column = await ds.addColumn(name);
    }
    await ds.updateSettings({ mapping: { ...mapping, [key]: column || undefined } });
  };

  if (!ds.loaded) return <p className="muted">Lade …</p>;
  if (!state) {
    return (
      <div className="card">
        <p>{ds.gone ? "Dieser Datensatz oder Link ist nicht (mehr) verfügbar." : ds.online ? "Daten werden geladen …" : "Offline - dieser Datensatz wurde noch nie auf dieses Gerät geladen."}</p>
        {ds.expired && <p className="warn">Sitzung abgelaufen. Bitte neu anmelden.</p>}
        {ds.error && <p className="error">{ds.error}</p>}
      </div>
    );
  }

  return (
    <div className="cable">
      <div className="toolbar">
        <h2>{state.name}</h2>
        <span className={`chip ${ds.online ? "ok" : "off"}`}>{ds.online ? "online" : "offline"}</span>
        {ds.pending > 0 && <span className="chip warn">{ds.pending} nicht übertragen</span>}
        {!canEdit && <span className="chip">nur lesen</span>}
        <span className="spacer" />
        <button onClick={() => void ds.syncNow()} disabled={ds.syncing}>{ds.syncing ? "Sync …" : "Synchronisieren"}</button>
        <button onClick={() => setShowAnalysis((v) => !v)}>Analyse</button>
        {canEdit && !backend.share && <button onClick={() => setShowSettings((v) => !v)}>Spalten</button>}
        {actions}
      </div>

      {ds.expired && <div className="banner warn">Sitzung abgelaufen - Änderungen bleiben lokal gespeichert. <a href="/login">Neu anmelden</a></div>}
      {ds.error && <div className="banner error">{ds.error}</div>}
      {ds.conflicts.length > 0 && !backend.share && (
        <div className="banner warn">
          {ds.conflicts.length} Änderung(en) kollidierten mit einer anderen Eingabe. Der Server-Wert bleibt vorerst bestehen,
          deine Eingabe liegt zur Entscheidung vor. <a href={`${location.pathname}?tab=conflicts`}>Konflikte ansehen und entscheiden</a>
        </div>
      )}

      {showSettings && (
        <fieldset className="card settings">
          <legend>Spaltenzuordnung und Optionen</legend>
          {!complete && <p className="warn">Bitte zuordnen, welche Spalte welche Bedeutung hat.</p>}
          <div className="grid2">
            {MAPPING_FIELDS.map((f) => (
              <label key={f.key}>
                {f.label}{f.required ? " *" : ""}
                <select value={mapping[f.key] ?? ""} onChange={(e) => void setMapping(f.key, e.target.value)}>
                  <option value="">– nicht gewählt –</option>
                  {columns.map((c, i) => <option key={c} value={c}>{excelLetter(i)} – {c}</option>)}
                  <option value="__new__">+ Neue Spalte anlegen</option>
                </select>
              </label>
            ))}
          </div>
          <label className="check">
            <input type="checkbox" checked={autoDate} onChange={(e) => void ds.updateSettings({ auto_date: e.target.checked })} />
            Auto-Datum: gezogene Kabel erhalten das heutige Datum (TT.MM.JJ)
          </label>
          <label className="check">
            <input type="checkbox" checked={opts.ignoreShort} onChange={(e) => void ds.updateSettings({ ignore_short: e.target.checked })} />
            Kurze Enden ignorieren, kürzer als
            <input type="number" min={0} step="0.5" value={opts.minLength} className="narrow"
              onChange={(e) => void ds.updateSettings({ min_length: Number(e.target.value) })} /> m
          </label>
        </fieldset>
      )}

      <div className="progress-strip" onClick={() => setShowAnalysis((v) => !v)}>
        <div className="pct">{complete ? `${pct.toFixed(1).replace(".", ",")} %` : "–"}</div>
        <div className="bar"><div style={{ width: `${pct}%` }} /></div>
        <div className="muted">
          {total ? `${total.done} von ${total.total} gezogen · noch ${total.total - total.done} offen${analysis!.ignored ? ` · ${analysis!.ignored} kurze Enden ignoriert` : ""}` : "Spalten zuordnen für die Analyse"}
        </div>
      </div>

      {showAnalysis && analysis && (
        <div className="card table-wrap">
          <table className="analysis">
            <thead><tr><th>Querschnitt</th><th>Gezogen</th><th>Offen</th><th>Stand %</th><th>Meter offen</th><th>Meter %</th></tr></thead>
            <tbody>
              {[...analysis.groups, analysis.total].map((g) => (
                <tr key={g.label} className={g.label === "Gesamt" ? "total" : ""}>
                  <td>{g.label}</td><td>{g.done} / {g.total}</td><td>{g.total - g.done}</td>
                  <td>{percent(g.done, g.total).toFixed(1).replace(".", ",")}</td>
                  <td>{formatNumber(Math.max(g.metersTotal - g.metersDone, 0))}</td>
                  <td>{percent(g.metersDone, g.metersTotal).toFixed(1).replace(".", ",")}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      <div className="panes">
        <section className="focus card">
          {selected && complete ? (
            <>
              <div className="focus-head">
                <span className="focus-id">{display(selected.data[mapping.cable_id!])}</span>
                <span className="focus-qs">{display(selected.data[mapping.cross_section!])}</span>
                <span className="focus-soll">Soll {display(selected.data[mapping.target_length!])} m</span>
                <span className={`chip st-${rowState(selected.data, mapping, opts)}`}>{STATE_LABEL[rowState(selected.data, mapping, opts)]}</span>
              </div>
              <div className="inputs">
                <label>Von (m)
                  <input ref={startRef} inputMode="decimal" value={startText} disabled={!canEdit} placeholder="Von"
                    onChange={(e) => { dirty.current = true; setStartText(e.target.value); }}
                    onKeyDown={(e) => { if (e.key === "Enter") { e.preventDefault(); void commit(); endRef.current?.focus(); } }}
                    onBlur={() => void commit()} />
                </label>
                <label>Bis (m)
                  <input ref={endRef} inputMode="decimal" value={endText} disabled={!canEdit} placeholder="Bis"
                    onChange={(e) => { dirty.current = true; setEndText(e.target.value); }}
                    onKeyDown={(e) => { if (e.key === "Enter") { e.preventDefault(); void finish(); } }}
                    onBlur={() => void commit()} />
                </label>
                <div className="length"><span>Länge</span><b>{length === null ? "–" : `${formatNumber(length)} m`}</b></div>
                {mapping.date && (
                  <label className="span2">Datum (TT.MM.JJ)
                    <span className="inline">
                      <input ref={dateRef} value={dateText} disabled={!canEdit} placeholder="30.12.26"
                        onChange={(e) => { dirty.current = true; setDateText(e.target.value); }}
                        onKeyDown={(e) => { if (e.key === "Enter") { e.preventDefault(); void finish(); } }}
                        onBlur={() => void commit()} />
                      <button type="button" disabled={!canEdit} onClick={() => { dirty.current = true; setDateText(shortDate()); setTimeout(() => dateRef.current?.focus(), 0); }}>Heute</button>
                    </span>
                  </label>
                )}
              </div>
              <div className="nav-buttons">
                <button onClick={() => step(-1)}>↑ Zurück</button>
                <button className="primary" disabled={!canEdit} onClick={() => void finish()}>Speichern &amp; weiter ↓</button>
                <button onClick={() => step(1)}>Weiter ↓</button>
                {canEdit && <button onClick={() => { dirty.current = true; setStartText(""); setEndText(""); setDateText(""); setTimeout(() => void commit(), 0); }}>Zurücksetzen</button>}
              </div>
              <details>
                <summary>Alle Felder</summary>
                <div className="fields">
                  {columns.map((c) => (
                    <label key={c}>{c}
                      <input defaultValue={display(selected.data[c])} key={`${selected.id}-${selected.rev}-${c}`} disabled={!canEdit} data-skip-nav="1"
                        onBlur={(e) => { const v = toCell(e.target.value); if (display(v) !== display(selected.data[c])) void ds.edit(selected.id, { [c]: v }); }} />
                    </label>
                  ))}
                </div>
              </details>
            </>
          ) : (
            <p className="muted">{complete ? "Kein Kabel gewählt." : "Spalten zuordnen, um mit dem Kabelzug zu beginnen."}</p>
          )}
        </section>

        <section className="list">
          <div className="filters">
            <input id="search" type="search" placeholder="Suchen …" value={query} onChange={(e) => { setQuery(e.target.value); setLimit(RENDER_LIMIT); }} />
            {(["all", "open", "done"] as Filter[]).map((f) => (
              <button key={f} className={filter === f ? "active" : ""} onClick={() => { setFilter(f); setLimit(RENDER_LIMIT); }}>
                {{ all: "Alle", open: "Offen", done: "Gezogen" }[f]}
              </button>
            ))}
            <span className="muted">{visible.length} Zeilen</span>
          </div>
          <div className="table-wrap tall">
            <table className="data">
              <thead><tr>{columns.map((c) => <th key={c}>{c}</th>)}</tr></thead>
              <tbody>
                {visible.slice(0, limit).map((r) => (
                  <tr key={r.id} id={`row-${r.id}`} className={`${r.id === selectedId ? "sel" : ""} st-${complete ? rowState(r.data, mapping, opts) : "open"}`}
                    onClick={() => void select(r.id)}>
                    {columns.map((c) => <td key={c}>{display(r.data[c])}</td>)}
                  </tr>
                ))}
              </tbody>
            </table>
            {visible.length > limit && <button onClick={() => setLimit((l) => l + RENDER_LIMIT)}>Mehr anzeigen ({visible.length - limit})</button>}
          </div>
        </section>
      </div>
    </div>
  );
}
