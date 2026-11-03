import { useCallback, useEffect, useMemo, useState } from "react";

export const ROUTE_KEY = "__route__";
export const ROUTE_LABEL = "Von → Nach";
const DEFAULT_WIDTH = 140;
const MIN_WIDTH = 50;

export interface SavedLayout { order: string[]; hidden: string[]; widths: Record<string, number> }
type Saved = SavedLayout;

export interface TableLayout {
  /** sichtbare Spalten in Anzeigereihenfolge */
  cols: string[];
  /** alle Spalten in Anzeigereihenfolge (auch ausgeblendete) */
  all: string[];
  hidden: Set<string>;
  width: (key: string) => number;
  setWidth: (key: string, w: number) => void;
  toggle: (key: string) => void;
  move: (key: string, delta: number) => void;
  /** Spalte `key` an die Position von `target` verschieben (Drag & Drop) */
  moveTo: (key: string, target: string) => void;
  reset: () => void;
  /** true: eigene Ansicht auf diesem Gerät (sonst Standard des Datensatzes bzw. Grundeinstellung) */
  customized: boolean;
  /** aktuelle Ansicht als speicherbares Layout */
  snapshot: () => SavedLayout;
}

function load(storeKey: string): Saved | null {
  try {
    const v = JSON.parse(localStorage.getItem(storeKey) ?? "null");
    return v && Array.isArray(v.order) ? { order: v.order, hidden: v.hidden ?? [], widths: v.widths ?? {} } : null;
  } catch { return null; }
}

/**
 * Spaltenlayout der Kabelzug-Tabelle (Reihenfolge, Sichtbarkeit, Breite).
 * Wird je Gerät und Datensatz im Browser gespeichert, damit jede Person ihre eigene Ansicht behält.
 * `defaults`: Reihenfolge ohne gespeichertes Layout; `defaultHidden`: dort ausgeblendete Spalten.
 */
export function useTableLayout(
  storeKey: string, defaults: string[], defaultHidden: string[], defaultWidths: Record<string, number>,
  sharedDefault: SavedLayout | null = null,
): TableLayout {
  const [local, setSaved] = useState<Saved | null>(() => load(storeKey));
  const sharedKey = JSON.stringify(sharedDefault);
  // eslint-disable-next-line react-hooks/exhaustive-deps
  const shared = useMemo(() => sharedDefault, [sharedKey]);
  const saved = local ?? shared; // eigene Ansicht vor Standard des Datensatzes
  useEffect(() => setSaved(load(storeKey)), [storeKey]);

  const persist = useCallback((next: Saved | null) => {
    setSaved(next);
    try {
      if (next) localStorage.setItem(storeKey, JSON.stringify(next)); else localStorage.removeItem(storeKey);
    } catch { /* Speicher gesperrt: Layout gilt nur für diese Sitzung */ }
  }, [storeKey]);

  const defaultsKey = defaults.join("\u0001");
  const hiddenKey = defaultHidden.join("\u0001");
  const all = useMemo(() => {
    if (!saved) return defaults;
    const known = saved.order.filter((k) => defaults.includes(k));
    return [...known, ...defaults.filter((k) => !known.includes(k))]; // neue Spalten hinten anfügen
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [saved, defaultsKey]);
  const hidden = useMemo(
    () => new Set(saved ? saved.hidden : defaultHidden),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [saved, hiddenKey],
  );
  const cols = useMemo(() => all.filter((k) => !hidden.has(k)), [all, hidden]);

  const width = (key: string) => saved?.widths[key] ?? defaultWidths[key] ?? DEFAULT_WIDTH;
  const current = (): Saved => saved ?? { order: all, hidden: [...hidden], widths: {} };
  return {
    cols, all, hidden, customized: !!local,
    snapshot: () => ({ order: all, hidden: [...hidden], widths: Object.fromEntries(all.map((k) => [k, width(k)])) }),
    width,
    setWidth: (key, w) => {
      const c = current();
      persist({ ...c, order: c.order.length ? c.order : all, widths: { ...c.widths, [key]: Math.max(MIN_WIDTH, Math.round(w)) } });
    },
    toggle: (key) => {
      const c = current();
      const h = new Set(c.hidden);
      if (h.has(key)) h.delete(key); else if (cols.length > 1) h.add(key); // mindestens eine Spalte bleibt sichtbar
      persist({ ...c, order: all, hidden: [...h] });
    },
    move: (key, delta) => {
      const c = current();
      const order = [...all];
      const i = order.indexOf(key), j = i + delta;
      if (i < 0 || j < 0 || j >= order.length) return;
      [order[i], order[j]] = [order[j], order[i]];
      persist({ ...c, order });
    },
    moveTo: (key, target) => {
      if (key === target) return;
      const c = current();
      const order = all.filter((k) => k !== key);
      const at = order.indexOf(target);
      if (at < 0) return;
      order.splice(all.indexOf(target) > all.indexOf(key) ? at + 1 : at, 0, key);
      persist({ ...c, order });
    },
    reset: () => persist(null),
  };
}

export function TableLayoutPanel({ layout, labelOf, hasShared, onShare, onClearShared }: {
  layout: TableLayout;
  labelOf: (key: string) => string;
  hasShared: boolean;
  /** nur für Bearbeiter: aktuelle Ansicht als Standard für alle speichern */
  onShare?: () => void;
  onClearShared?: () => void;
}) {
  return (
    <fieldset className="card settings">
      <legend>Tabelle anpassen</legend>
      <p className="muted">
        Sichtbarkeit, Reihenfolge und Breite der Spalten. Die Ansicht wird auf diesem Gerät gespeichert.
        Die Breite lässt sich auch direkt am Spaltenrand der Tabelle ziehen.
      </p>
      <ul className="plain col-config">
        {layout.all.map((key, i) => (
          <li key={key} draggable onDragStart={(e) => e.dataTransfer.setData("text/plain", key)}
            onDragOver={(e) => e.preventDefault()}
            onDrop={(e) => { e.preventDefault(); layout.moveTo(e.dataTransfer.getData("text/plain"), key); }}>
            <span className="grip" title="Ziehen zum Umsortieren" aria-hidden>⠿</span>
            <label className="check">
              <input type="checkbox" checked={!layout.hidden.has(key)} onChange={() => layout.toggle(key)} />
              {labelOf(key)}
            </label>
            <span className="spacer" />
            <label className="inline-num">Breite
              <input type="number" min={50} max={800} step={10} value={layout.width(key)}
                onChange={(e) => { const n = Number(e.target.value); if (n >= 50) layout.setWidth(key, n); }} />
            </label>
            <button type="button" disabled={i === 0} onClick={() => layout.move(key, -1)} aria-label="nach oben">↑</button>
            <button type="button" disabled={i === layout.all.length - 1} onClick={() => layout.move(key, 1)} aria-label="nach unten">↓</button>
          </li>
        ))}
      </ul>
      <div className="row-buttons">
        <button type="button" disabled={!layout.customized} onClick={layout.reset}>
          {hasShared ? "Eigene Ansicht verwerfen (Standard des Datensatzes)" : "Standardansicht wiederherstellen"}
        </button>
        {onShare && <button type="button" onClick={onShare}>Aktuelle Ansicht als Standard für alle speichern</button>}
        {onClearShared && hasShared && <button type="button" onClick={onClearShared}>Gemeinsamen Standard entfernen</button>}
      </div>
      <p className="muted">
        {layout.customized ? "Du nutzt eine eigene Ansicht auf diesem Gerät." : hasShared ? "Es gilt der gemeinsame Standard des Datensatzes." : "Es gilt die Grundansicht."}
      </p>
    </fieldset>
  );
}
