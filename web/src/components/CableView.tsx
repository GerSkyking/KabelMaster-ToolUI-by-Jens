import { ReactNode, useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  GroupBy, Mapping, MAPPING_FIELDS, analyze, computeLength, crossSections, display, excelLetter, formatNumber, mappingComplete,
  parseNumber, percent, plausibility, rowState, sectionLabel, shortDate, RowState,
} from "../cable";
import type { LocalRow } from "../db";
import { Backend } from "../sync";
import { useDataset } from "../useDataset";
import { SectionFilter } from "./SectionFilter";
import { ROUTE_KEY, ROUTE_LABEL, TableLayoutPanel, useTableLayout } from "./TableLayout";

const RENDER_LIMIT = 300;
type Filter = "all" | "open" | "done" | "ignored";
const FILTERS: Filter[] = ["all", "open", "done", "ignored"];

interface SavedView { filter: Filter; query: string; sections: string[] | null; targets: string[] | null }

/** Filteransicht pro Gerät und Datensatz: übersteht Neuladen der Seite. */
function loadView(key: string): SavedView {
  const empty: SavedView = { filter: "all", query: "", sections: null, targets: null };
  try {
    const v = JSON.parse(localStorage.getItem(key) ?? "null");
    if (!v) return empty;
    const list = (x: unknown) => (Array.isArray(x) ? x.map(String) : null);
    return {
      filter: FILTERS.includes(v.filter) ? v.filter : "all",
      query: typeof v.query === "string" ? v.query : "",
      sections: list(v.sections), targets: list(v.targets),
    };
  } catch { return empty; }
}

function toCell(text: string): string | number | null {
  const t = text.trim();
  if (!t) return null;
  return /^-?\d+([.,]\d+)?$/.test(t) ? Number(t.replace(",", ".")) : t;
}

const STATE_LABEL: Record<RowState, string> = { open: "offen", done: "gezogen", ignored: "ignoriert" };

/** "Ziel 1 → Ziel 2" eines Kabels; leer, wenn keine Ziele zugeordnet oder eingetragen sind. */
function routeOf(data: Record<string, unknown>, mapping: Mapping): string {
  const a = mapping.target1 ? display(data[mapping.target1]).trim() : "";
  const b = mapping.target2 ? display(data[mapping.target2]).trim() : "";
  return a || b ? `${a || "?"} → ${b || "?"}` : "";
}

const FILTER_LABEL: Record<Filter, string> = { all: "Alle", open: "Offen", done: "Gezogen", ignored: "Ignoriert" };

/** Zellen, die Excel als Formel deuten würde, entschärfen (CSV-Injection). */
function csvCell(text: string): string {
  const safe = /^[=+@\t\r]|^-(?!\d)/.test(text) ? `'${text}` : text;
  return `"${safe.replace(/"/g, '""')}"`;
}

const escapeHtml = (s: string) => s.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");

export function CableView({ backend, actions }: { backend: Backend; actions?: ReactNode }) {
  const ds = useDataset(backend);
  const { state, rows } = ds;
  const columns = state?.columns ?? [];
  const mapping: Mapping = state?.settings.mapping ?? {};
  const opts = {
    ignoreShort: !!state?.settings.ignore_short,
    minLength: state?.settings.min_length ?? 2,
    ignoreNoTarget: !!state?.settings.ignore_no_target,
  };
  const autoDate = !!state?.settings.auto_date;
  const canEdit = !!state?.canEdit;
  const complete = mappingComplete(mapping, columns);

  const [selectedId, setSelectedId] = useState<number | null>(null);
  const viewKey = `cable-view:${backend.key}`;
  const initialView = useMemo(() => loadView(viewKey), [viewKey]);
  const [filter, setFilter] = useState<Filter>(initialView.filter);
  const [query, setQuery] = useState(initialView.query);
  const [showSettings, setShowSettings] = useState(false);
  const [showAnalysis, setShowAnalysis] = useState(false);
  const [showTable, setShowTable] = useState(false);
  const [sections, setSections] = useState<Set<string> | null>(initialView.sections && new Set(initialView.sections));
  const [targets, setTargets] = useState<Set<string> | null>(initialView.targets && new Set(initialView.targets));
  const [dragCol, setDragCol] = useState<string | null>(null);
  const touchDrag = useRef<{ timer?: number; active: boolean; over?: string }>({ active: false });
  const [groupBy, setGroupBy] = useState<GroupBy>("section");
  const [allDone, setAllDone] = useState(false);
  const endKey = `cable-lastend:${backend.key}`;
  const [lastEnd, setLastEnd] = useState(() => { try { return localStorage.getItem(endKey) ?? ""; } catch { return ""; } });
  const [undo, setUndo] = useState<{ id: number; patch: Record<string, unknown> } | null>(null);
  const wrapRef = useRef<HTMLDivElement>(null);
  const sentinelRef = useRef<HTMLDivElement>(null);
  const [minText, setMinText] = useState<string | null>(null);
  const [limit, setLimit] = useState(RENDER_LIMIT);
  const [startText, setStartText] = useState("");
  const [endText, setEndText] = useState("");
  const [dateText, setDateText] = useState("");
  const dirty = useRef(false);
  const startRef = useRef<HTMLInputElement>(null);
  const endRef = useRef<HTMLInputElement>(null);
  const dateRef = useRef<HTMLInputElement>(null);

  // Analyse und Fortschritt gelten für die gewählten Querschnitte/Ziele (ohne Auswahl für alles)
  const scoped = !!(sections || targets);
  const analysis = useMemo(() => {
    if (!complete) return null;
    const inScope = rows.filter((r) => {
      if (sections && !sections.has(sectionLabel(r.data, mapping))) return false;
      if (targets) {
        const ts = [mapping.target1, mapping.target2].map((c) => (c ? display(r.data[c]).trim() : ""));
        if (!ts.some((t) => targets.has(t))) return false;
      }
      return true;
    });
    return analyze(inScope.map((r) => r.data), mapping, opts, groupBy);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [rows, state?.settings, complete, sections, targets, groupBy]);

  useEffect(() => {
    try {
      localStorage.setItem(viewKey, JSON.stringify({
        filter, query, sections: sections && [...sections], targets: targets && [...targets],
      }));
    } catch { /* Speicher gesperrt: Ansicht gilt nur für diese Sitzung */ }
  }, [viewKey, filter, query, sections, targets]);

  const hasRouteColumns = !!((mapping.target1 && columns.includes(mapping.target1)) || (mapping.target2 && columns.includes(mapping.target2)));
  const targetOptions = useMemo(() => {
    const set = new Set<string>();
    for (const r of rows) for (const c of [mapping.target1, mapping.target2]) {
      const v = c ? display(r.data[c]).trim() : "";
      if (v) set.add(v);
    }
    return [...set].sort((a, b) => a.localeCompare(b, "de", { numeric: true }));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [rows, mapping.target1, mapping.target2]);

  const sectionOptions = useMemo(
    () => (complete ? crossSections(rows.map((r) => r.data), mapping) : []),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [rows, mapping.cross_section, complete]);

  // Gespeicherte Auswahl, die es nicht mehr gibt (z. B. nach Umbenennung), nicht stillschweigend weiterfiltern
  useEffect(() => {
    if (!complete || !rows.length) return;
    const prune = (sel: Set<string> | null, options: string[]) => {
      if (!sel || !sel.size) return sel;
      const kept = [...sel].filter((v) => options.includes(v));
      return kept.length === sel.size ? sel : kept.length ? new Set(kept) : null;
    };
    setSections((s) => prune(s, sectionOptions));
    if (hasRouteColumns) setTargets((t) => prune(t, targetOptions));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [sectionOptions, targetOptions, complete, rows.length]);

  // Ignorierte Kabel (kurze Enden / ohne Soll-Meter) bleiben in der Liste, stehen aber am Ende
  const visible = useMemo(() => {
    const terms = query.trim().toLowerCase().split(/\s+/).filter(Boolean);
    const active: LocalRow[] = [], ignored: LocalRow[] = [];
    for (const r of rows) {
      const s: RowState = complete ? rowState(r.data, mapping, opts) : "open";
      if (complete && filter === "open" && s !== "open") continue;
      if (complete && filter === "done" && s !== "done") continue;
      if (complete && filter === "ignored" && s !== "ignored") continue;
      if (targets) {
        const ts = [mapping.target1, mapping.target2].map((c) => (c ? display(r.data[c]).trim() : ""));
        if (!ts.some((t) => targets.has(t))) continue;
      }
      if (complete && sections && !sections.has(sectionLabel(r.data, mapping))) continue;
      if (terms.length) {
        const hay = [...Object.values(r.data).map(display), routeOf(r.data, mapping)].join(" ").toLowerCase();
        if (!terms.every((t) => hay.includes(t))) continue;
      }
      (s === "ignored" ? ignored : active).push(r);
    }
    return [...active, ...ignored];
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [rows, filter, query, sections, targets, state?.settings, complete]);

  // Tabellenlayout (Reihenfolge, Sichtbarkeit, Breite) - je Gerät und Datensatz gespeichert
  const hasRoute = !!(mapping.target1 && columns.includes(mapping.target1)) || !!(mapping.target2 && columns.includes(mapping.target2));
  const layoutDefaults = useMemo(() => {
    const base = [...columns];
    if (hasRoute) {
      const at = mapping.cable_id ? base.indexOf(mapping.cable_id) : -1;
      base.splice(at + 1, 0, ROUTE_KEY);
    }
    return base;
  }, [columns, hasRoute, mapping.cable_id]);
  const layoutHidden = useMemo(
    () => (hasRoute ? [mapping.target1, mapping.target2].filter((c): c is string => !!c && columns.includes(c)) : []),
    [columns, hasRoute, mapping.target1, mapping.target2]);
  const layoutWidths = useMemo(
    () => ({ [ROUTE_KEY]: 240, ...(mapping.cable_id ? { [mapping.cable_id]: 150 } : {}) }),
    [mapping.cable_id]);
  const layout = useTableLayout(`cable-layout:${backend.key}`, layoutDefaults, layoutHidden, layoutWidths, state?.settings.table_layout ?? null);
  const labelOf = (key: string) => (key === ROUTE_KEY ? ROUTE_LABEL : key);
  const cellText = (data: Record<string, unknown>, key: string) => (key === ROUTE_KEY ? routeOf(data, mapping) : display(data[key]));
  const tableWidth = layout.cols.reduce((sum, k) => sum + layout.width(k), 0);

  // Spaltenbreite per Ziehen am rechten Rand der Überschrift
  // Spalten per Finger umsortieren: Kopfzelle lange drücken, dann auf die Zielspalte ziehen
  const colAt = (x: number, y: number) => (document.elementFromPoint(x, y) as HTMLElement | null)?.closest<HTMLElement>("th[data-col]")?.dataset.col;
  const headTouchDown = (c: string, e: React.PointerEvent) => {
    if (e.pointerType === "mouse") return;
    const t = touchDrag.current;
    window.clearTimeout(t.timer);
    t.active = false;
    t.timer = window.setTimeout(() => { t.active = true; t.over = c; setDragCol(c); navigator.vibrate?.(20); }, 450);
  };
  const headTouchMove = (e: React.PointerEvent) => {
    const t = touchDrag.current;
    if (!t.active) { if (Math.abs(e.movementX) + Math.abs(e.movementY) > 6) window.clearTimeout(t.timer); return; }
    t.over = colAt(e.clientX, e.clientY) ?? t.over;
  };
  const headTouchEnd = () => {
    const t = touchDrag.current;
    window.clearTimeout(t.timer);
    if (t.active && dragCol && t.over) layout.moveTo(dragCol, t.over);
    t.active = false;
    setDragCol(null);
  };
  useEffect(() => {
    // Während des Ziehens darf die Tabelle nicht mitscrollen
    const block = (e: TouchEvent) => { if (touchDrag.current.active) e.preventDefault(); };
    document.addEventListener("touchmove", block, { passive: false });
    return () => document.removeEventListener("touchmove", block);
  }, []);

  const startResize = (key: string, e: React.PointerEvent) => {
    e.preventDefault();
    e.stopPropagation();
    const th = e.currentTarget.parentElement as HTMLElement;
    const startX = e.clientX, startW = layout.width(key);
    let latest = startW;
    const move = (ev: PointerEvent) => { latest = Math.max(50, startW + ev.clientX - startX); th.style.width = `${latest}px`; };
    const up = () => { window.removeEventListener("pointermove", move); window.removeEventListener("pointerup", up); layout.setWidth(key, latest); };
    window.addEventListener("pointermove", move);
    window.addEventListener("pointerup", up);
  };

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
  // Beim Öffnen wieder beim zuletzt bearbeiteten Kabel starten
  const lastKey = `cable-last:${backend.key}`;
  useEffect(() => {
    if (selectedId !== null || !rows.length) return;
    let id = rows[0].id;
    try {
      const saved = Number(localStorage.getItem(lastKey));
      if (rows.some((r) => r.id === saved)) id = saved;
    } catch { /* Speicher gesperrt */ }
    setSelectedId(id);
    setTimeout(() => document.getElementById(`row-${id}`)?.scrollIntoView({ block: "center" }), 150);
  }, [rows, selectedId, lastKey]);
  useEffect(() => {
    if (selectedId === null) return;
    try { localStorage.setItem(lastKey, String(selectedId)); } catch { /* Speicher gesperrt */ }
  }, [selectedId, lastKey]);
  // Auswahl jenseits des bisher gerenderten Bereichs: Liste so weit nachladen
  useEffect(() => {
    const i = visible.findIndex((r) => r.id === selectedId);
    if (i >= limit) setLimit(i + RENDER_LIMIT);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedId]);

  // Weitere Zeilen automatisch nachladen, sobald man ans Listenende scrollt
  const hasMore = visible.length > limit;
  useEffect(() => {
    const el = sentinelRef.current, root = wrapRef.current;
    if (!el || !root || !hasMore) return;
    const io = new IntersectionObserver((entries) => {
      if (entries.some((e) => e.isIntersecting)) setLimit((l) => l + RENDER_LIMIT);
    }, { root, rootMargin: "300px" });
    io.observe(el);
    return () => io.disconnect();
  }, [hasMore, limit, ds.loaded, !!state]); // eslint-disable-line react-hooks/exhaustive-deps

  // Rückgängig-Hinweis nach "Zurücksetzen" verschwindet nach 10 Sekunden
  useEffect(() => {
    if (!undo) return;
    const t = window.setTimeout(() => setUndo(null), 10_000);
    return () => window.clearTimeout(t);
  }, [undo]);

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
    if (endText.trim()) {
      setLastEnd(endText.trim());
      try { localStorage.setItem(endKey, endText.trim()); } catch { /* Speicher gesperrt */ }
    }
    if (Object.keys(patch).length) await ds.edit(selected.id, patch);
  }, [selected, canEdit, complete, mapping, startText, endText, dateText, autoDate, ds]);

  const select = useCallback(async (id: number) => {
    await commit();
    setSelectedId(id);
    setTimeout(() => {
      // Einspaltiges Layout (Handy/Tablet hochkant): Eingabekarte liegt über der Liste, also dorthin scrollen
      if (window.matchMedia("(max-width: 1099px)").matches) document.getElementById("cable-focus")?.scrollIntoView({ block: "start", behavior: "smooth" });
      else document.getElementById(`row-${id}`)?.scrollIntoView({ block: "nearest" });
    }, 0);
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
    const isOpen = (r: LocalRow) => complete && rowState(r.data, mapping, opts) === "open";
    // Gezogen-/Ignoriert-Ansicht: einfach das nächste Listenelement; sonst das nächste offene Kabel (ab Ende wieder von vorn)
    const next = filter === "done" || filter === "ignored" || !complete
      ? visible[index + 1]
      : visible.slice(index + 1).find(isOpen) ?? visible.slice(0, Math.max(index, 0)).find(isOpen);
    setAllDone(!next && complete && filter !== "done" && filter !== "ignored" && !!visible.length);
    if (next) setSelectedId(next.id);
    setTimeout(() => {
      if (next) document.getElementById(`row-${next.id}`)?.scrollIntoView({ block: "nearest" });
      startRef.current?.focus();
      startRef.current?.select();
    }, 0);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [commit, visible, selectedId, complete, filter, state?.settings]);
  useEffect(() => setAllDone(false), [selectedId, filter, sections, targets, query]);

  // Pfeiltasten wählen das Kabel - auch aus den Eingabefeldern heraus
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const target = e.target as HTMLElement;
      // In allen anderen Eingabefeldern (Suche, Dropdowns, Einstellungen, Tabellenlayout) gehören die Tasten dem Feld
      const typing = ["INPUT", "SELECT", "TEXTAREA"].includes(target.tagName) && !target.closest(".inputs");
      if (typing || target.isContentEditable || target.dataset.skipNav === "1") return;
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
  // Letzte eingegebene Bis-Zahl (sonst das Bis des vorherigen Kabels in der Liste) als Von übernehmen
  const previousEnd = (() => {
    const index = visible.findIndex((r) => r.id === selectedId);
    for (let i = index - 1; i >= 0 && mapping.end; i--) {
      const v = display(visible[i].data[mapping.end]).trim();
      if (v) return v;
    }
    return "";
  })();
  const takeEnd = lastEnd || previousEnd;
  const takeLastEnd = (
    <button type="button" disabled={!canEdit || !takeEnd} title="Letzte Bis-Zahl als Von übernehmen"
      onClick={() => { dirty.current = true; setStartText(takeEnd); setTimeout(() => endRef.current?.focus(), 0); }}>
      Von = {takeEnd || "–"}
    </button>
  );
  const warning = selected && complete ? plausibility(selected.data[mapping.target_length!], startText, endText) : null;

  const resetCable = () => {
    if (!selected || !canEdit || !complete) return;
    const keys = [mapping.start, mapping.end, mapping.pulled_length, mapping.date].filter((k): k is string => !!k);
    const before = Object.fromEntries(keys.map((k) => [k, selected.data[k] ?? null]));
    const patch = Object.fromEntries(keys.filter((k) => display(selected.data[k]) !== "").map((k) => [k, null]));
    dirty.current = false;
    setStartText(""); setEndText(""); setDateText("");
    if (Object.keys(patch).length) {
      setUndo({ id: selected.id, patch: before });
      void ds.edit(selected.id, patch);
    }
  };
  const undoReset = () => {
    if (!undo) return;
    void ds.edit(undo.id, undo.patch);
    setUndo(null);
  };

  const filtered = filter !== "all" || !!query.trim() || !!sections || !!targets;
  const resetFilters = () => { setFilter("all"); setQuery(""); setSections(null); setTargets(null); setLimit(RENDER_LIMIT); };

  const viewDescription = () => {
    const parts = filter === "all" ? [] : [FILTER_LABEL[filter]];
    if (sections) parts.push(`Querschnitt: ${[...sections].join(", ") || "keiner"}`);
    if (targets) parts.push(`Ziel: ${[...targets].join(", ") || "keines"}`);
    if (query.trim()) parts.push(`Suche: ${query.trim()}`);
    return parts.join(" · ");
  };

  /** Aktuelle Ansicht (Filter, Sortierung, Spaltenreihenfolge) als CSV für Excel */
  const exportCsv = () => {
    const lines = [
      layout.cols.map((c) => csvCell(labelOf(c))).join(";"),
      ...visible.map((r) => layout.cols.map((c) => csvCell(cellText(r.data, c))).join(";")),
    ];
    const blob = new Blob(["﻿" + lines.join("\r\n")], { type: "text/csv;charset=utf-8" });
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = `${(state?.name ?? "Kabelliste").replace(/[^\w.-]+/g, "_")}_Ansicht.csv`;
    a.click();
    setTimeout(() => URL.revokeObjectURL(a.href), 1000);
  };

  /** Aktuelle Ansicht drucken bzw. als PDF speichern (Druckdialog des Browsers) */
  const printView = () => {
    const title = escapeHtml(state?.name ?? "Kabelliste");
    const head = layout.cols.map((c) => `<th>${escapeHtml(labelOf(c))}</th>`).join("");
    const body = visible.map((r) => {
      const ignored = complete && rowState(r.data, mapping, opts) === "ignored";
      return `<tr${ignored ? " class=\"ign\"" : ""}>${layout.cols.map((c) => `<td>${escapeHtml(cellText(r.data, c))}</td>`).join("")}</tr>`;
    }).join("");
    const html = `<!doctype html><meta charset="utf-8"><title>${title}</title>
<style>body{font:11px/1.3 sans-serif;margin:12px}h3{margin:0 0 4px}p{margin:0 0 8px;color:#555}
table{border-collapse:collapse;width:100%}th,td{border:1px solid #999;padding:2px 5px;text-align:left}
th{background:#eee}thead{display:table-header-group}tr{page-break-inside:avoid}tr.ign td{color:#888}</style>
<h3>${title}</h3><p>${escapeHtml(viewDescription() || "Alle Kabel")} · ${visible.length} Kabel · ${new Date().toLocaleDateString("de-DE")}</p>
<table><thead><tr>${head}</tr></thead><tbody>${body}</tbody></table>`;
    if (window.matchMedia("(pointer: coarse)").matches) {
      // Smartphone/Tablet: Drucken im versteckten iframe ist dort unzuverlässig, also eigene Seite öffnen (Teilen > Drucken)
      const url = URL.createObjectURL(new Blob([html], { type: "text/html" }));
      if (!window.open(url, "_blank")) alert("Das Pop-up wurde blockiert. Bitte erlauben oder die CSV-Ausgabe nutzen.");
      setTimeout(() => URL.revokeObjectURL(url), 60000);
      return;
    }
    const frame = document.createElement("iframe");
    frame.style.cssText = "position:fixed;right:0;bottom:0;width:0;height:0;border:0";
    frame.onload = () => {
      frame.contentWindow?.focus();
      frame.contentWindow?.print();
      setTimeout(() => frame.remove(), 5000);
    };
    frame.srcdoc = html;
    document.body.appendChild(frame);
  };

  const total = analysis?.total;
  const rowWarning = (r: LocalRow) =>
    complete && rowState(r.data, mapping, opts) !== "ignored"
      ? plausibility(r.data[mapping.target_length!], r.data[mapping.start!], r.data[mapping.end!])
      : null;
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
        <button className={showTable ? "active" : ""} onClick={() => setShowTable((v) => !v)}>Tabelle</button>
        <button onClick={exportCsv} disabled={!visible.length} title="Aktuelle Liste (mit Filtern und Spaltenreihenfolge) als CSV für Excel">CSV</button>
        <button onClick={printView} disabled={!visible.length} title="Aktuelle Liste drucken oder als PDF speichern">Drucken</button>
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
            <input type="text" inputMode="decimal" className="narrow" aria-label="Mindestlänge in Metern"
              value={minText ?? formatNumber(opts.minLength)}
              onChange={(e) => {
                setMinText(e.target.value);
                const n = parseNumber(e.target.value);
                if (n !== null && n >= 0) void ds.updateSettings({ min_length: n });
              }}
              onBlur={() => setMinText(null)} /> m
          </label>
          <label className="check">
            <input type="checkbox" checked={opts.ignoreNoTarget} onChange={(e) => void ds.updateSettings({ ignore_no_target: e.target.checked })} />
            Kabel ohne Soll-Meter ignorieren (leer oder 0)
          </label>
          <p className="muted">Ignorierte Kabel zählen nicht in Analyse und Prognose; sie stehen ausgegraut am Ende der Liste.</p>
        </fieldset>
      )}

      {showTable && (
        <TableLayoutPanel layout={layout} labelOf={labelOf} hasShared={!!state.settings.table_layout}
          onShare={canEdit && !backend.share ? () => void ds.updateSettings({ table_layout: layout.snapshot() }) : undefined}
          onClearShared={canEdit && !backend.share ? () => void ds.updateSettings({ table_layout: null }) : undefined} />
      )}

      <div className="progress-strip" onClick={() => setShowAnalysis((v) => !v)}>
        <div className="pct">{complete ? `${pct.toFixed(1).replace(".", ",")} %` : "–"}</div>
        <div className="bar"><div style={{ width: `${pct}%` }} /></div>
        <div className="muted">
          {scoped && total ? <b>Auswahl: </b> : null}
          {total ? `${total.done} von ${total.total} gezogen · noch ${total.total - total.done} offen${analysis!.ignored ? ` · ${analysis!.ignored} ignoriert` : ""}` : "Spalten zuordnen für die Analyse"}
        </div>
      </div>

      {showAnalysis && analysis && (
        <div className="card table-wrap">
          <div className="filters">
            {hasRoute && (["section", "route"] as GroupBy[]).map((g) => (
              <button key={g} className={groupBy === g ? "active" : ""} onClick={() => setGroupBy(g)}>
                {g === "section" ? "Nach Querschnitt" : "Nach Strecke"}
              </button>
            ))}
            {scoped && <span className="muted">Nur die gewählten Querschnitte/Ziele</span>}
          </div>
          <table className="analysis">
            <thead><tr><th>{groupBy === "route" ? "Strecke" : "Querschnitt"}</th><th>Gezogen</th><th>Offen</th><th>Stand %</th><th>Meter offen</th><th>Meter %</th></tr></thead>
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
        <section className="focus card" id="cable-focus">
          {selected && complete ? (
            <>
              <div className="focus-head">
                <span className="focus-id">{display(selected.data[mapping.cable_id!])}</span>
                <span className="focus-qs">{display(selected.data[mapping.cross_section!])}</span>
                <span className="focus-soll">Soll {display(selected.data[mapping.target_length!])} m</span>
                <span className={`chip st-${rowState(selected.data, mapping, opts)}`}>{STATE_LABEL[rowState(selected.data, mapping, opts)]}</span>
              </div>
              {hasRoute && <div className="focus-route">{routeOf(selected.data, mapping) || "Keine Ziele eingetragen"}</div>}
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
                {!mapping.date && <div className="span2">{takeLastEnd}</div>}
                {mapping.date && (
                  <label className="span2">Datum (TT.MM.JJ)
                    <span className="inline">
                      <input ref={dateRef} value={dateText} disabled={!canEdit} placeholder="30.12.26"
                        onChange={(e) => { dirty.current = true; setDateText(e.target.value); }}
                        onKeyDown={(e) => { if (e.key === "Enter") { e.preventDefault(); void finish(); } }}
                        onBlur={() => void commit()} />
                      <button type="button" disabled={!canEdit} onClick={() => { dirty.current = true; setDateText(shortDate()); setTimeout(() => dateRef.current?.focus(), 0); }}>Heute</button>
                      {takeLastEnd}
                    </span>
                  </label>
                )}
              </div>
              {allDone && <div className="banner ok-banner" role="status">Alle Kabel in dieser Ansicht sind gezogen.</div>}
              {warning && <p className="warn plausibility" role="alert">⚠ {warning}</p>}
              <div className="nav-buttons">
                <button onClick={() => step(-1)}>↑ Zurück</button>
                <button className="primary" disabled={!canEdit} onClick={() => void finish()}>Speichern &amp; weiter ↓</button>
                <button onClick={() => step(1)}>Weiter ↓</button>
                {canEdit && <button onClick={resetCable}>Zurücksetzen</button>}
              </div>
              {undo && undo.id === selected.id && (
                <div className="banner warn">Kabel zurückgesetzt. <button type="button" onClick={undoReset}>Rückgängig</button></div>
              )}
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
            {complete && sectionOptions.length > 0 && (
              <SectionFilter options={sectionOptions} selected={sections} onChange={(s) => { setSections(s); setLimit(RENDER_LIMIT); }} />
            )}
            {hasRoute && targetOptions.length > 0 && (
              <SectionFilter options={targetOptions} selected={targets} noun="Ziel" nounPlural="Ziele"
                onChange={(s) => { setTargets(s); setLimit(RENDER_LIMIT); }} />
            )}
            {FILTERS.map((f) => (
              <button key={f} className={filter === f ? "active" : ""} onClick={() => { setFilter(f); setLimit(RENDER_LIMIT); }}>
                {FILTER_LABEL[f]}
              </button>
            ))}
            <span className="muted">{visible.length} Zeilen</span>
          </div>
          {filtered && (
            <div className="banner warn active-filters" role="status">
              <span>Filter aktiv: {viewDescription()}{!visible.length ? " – keine Treffer" : ""}</span>
              <button type="button" onClick={resetFilters}>Alle zurücksetzen</button>
            </div>
          )}
          <div className="table-wrap tall" ref={wrapRef}>
            <table className="data fixed" style={{ width: tableWidth }}>
              <thead>
                <tr>
                  {layout.cols.map((c) => (
                    <th key={c} data-col={c} style={{ width: layout.width(c) }} title={`${labelOf(c)} (zum Umsortieren ziehen)`} draggable
                      onPointerDown={(e) => headTouchDown(c, e)} onPointerMove={headTouchMove} onPointerUp={headTouchEnd} onPointerCancel={headTouchEnd}
                      className={dragCol === c ? "dragging" : ""}
                      onDragStart={(e) => { setDragCol(c); e.dataTransfer.setData("text/plain", c); }}
                      onDragEnd={() => setDragCol(null)}
                      onDragOver={(e) => e.preventDefault()}
                      onDrop={(e) => { e.preventDefault(); layout.moveTo(e.dataTransfer.getData("text/plain"), c); setDragCol(null); }}>
                      <span className="th-text">{labelOf(c)}</span>
                      <span className="resizer" onPointerDown={(e) => { e.stopPropagation(); startResize(c, e); }} onClick={(e) => e.stopPropagation()} aria-hidden />
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {visible.slice(0, limit).map((r) => (
                  <tr key={r.id} id={`row-${r.id}`} className={`${r.id === selectedId ? "sel" : ""} st-${complete ? rowState(r.data, mapping, opts) : "open"}`}
                    onClick={() => void select(r.id)}>
                    {layout.cols.map((c, i) => {
                      const t = cellText(r.data, c);
                      return <td key={c} title={t}>{i === 0 && rowWarning(r) ? <span className="warn-mark" title={rowWarning(r)!}>⚠ </span> : null}{t}</td>;
                    })}
                  </tr>
                ))}
              </tbody>
            </table>
            {hasMore && (
              <div ref={sentinelRef} className="more">
                <button onClick={() => setLimit((l) => l + RENDER_LIMIT)}>Mehr anzeigen ({visible.length - limit})</button>
              </div>
            )}
          </div>
        </section>
      </div>
    </div>
  );
}
