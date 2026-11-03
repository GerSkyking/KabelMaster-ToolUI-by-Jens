// Kabelzug-Logik. Spiegelt core/cable/cable_analysis.py (Desktop/Server), damit alle Clients gleich rechnen.

export type Row = Record<string, unknown>;

export interface Mapping {
  cable_id?: string;
  cross_section?: string;
  target_length?: string;
  start?: string;
  end?: string;
  pulled_length?: string;
  date?: string;
  target1?: string;
  target2?: string;
  forecast?: string;
  labeled1?: string;
  labeled2?: string;
}

export const MAPPING_FIELDS: { key: keyof Mapping; label: string; required: boolean; newName: string }[] = [
  { key: "cable_id", label: "Kabel (Bezeichnung)", required: true, newName: "Kabel" },
  { key: "cross_section", label: "Querschnitt", required: true, newName: "Querschnitt" },
  { key: "target_length", label: "Soll-Länge (m)", required: true, newName: "Soll-Länge" },
  { key: "start", label: "Von (Meterzahl)", required: true, newName: "Von (m)" },
  { key: "end", label: "Bis (Meterzahl)", required: true, newName: "Bis (m)" },
  { key: "pulled_length", label: "Gezogene Länge (Ergebnis)", required: true, newName: "Gezogen (m)" },
  { key: "date", label: "Datum", required: false, newName: "Datum" },
  { key: "target1", label: "Ziel 1 (für Prognose und KMK)", required: false, newName: "Ziel 1" },
  { key: "target2", label: "Ziel 2 (für Prognose und KMK)", required: false, newName: "Ziel 2" },
  { key: "forecast", label: "Prognostizierte Länge", required: false, newName: "prognostizierte Länge" },
  { key: "labeled1", label: "Beschriftet Ziel 1", required: false, newName: "beschriftet Ziel 1" },
  { key: "labeled2", label: "Beschriftet Ziel 2", required: false, newName: "beschriftet Ziel 2" },
];

const NUMBER_RE = /-?\d+(?:[.,]\d+)?/;

export function parseNumber(value: unknown): number | null {
  if (value === null || value === undefined || typeof value === "boolean") return null;
  if (typeof value === "number") return Number.isFinite(value) ? value : null;
  const match = NUMBER_RE.exec(String(value));
  return match ? Number(match[0].replace(",", ".")) : null;
}

/** Gezogene Länge aus den Meterzahlen auf dem Kabel: |Bis - Von|, null wenn eine fehlt. */
export function computeLength(start: unknown, end: unknown): number | null {
  const a = parseNumber(start);
  const b = parseNumber(end);
  if (a === null || b === null) return null;
  return Math.round(Math.abs(b - a) * 100) / 100;
}

export function formatNumber(value: number): string {
  return String(Math.round(value * 100) / 100).replace(".", ",");
}

export function display(value: unknown): string {
  if (value === null || value === undefined) return "";
  return typeof value === "number" ? formatNumber(value) : String(value);
}

/** Datum im Format TT.MM.JJ, z. B. 30.12.26 */
export function shortDate(date: Date = new Date()): string {
  const p = (n: number) => String(n).padStart(2, "0");
  return `${p(date.getDate())}.${p(date.getMonth() + 1)}.${p(date.getFullYear() % 100)}`;
}

export function excelLetter(index: number): string {
  let n = index + 1;
  let letters = "";
  while (n > 0) {
    const rem = (n - 1) % 26;
    letters = String.fromCharCode(65 + rem) + letters;
    n = Math.floor((n - 1) / 26);
  }
  return letters;
}

export interface CableOptions {
  ignoreShort: boolean;
  minLength: number;
  ignoreNoTarget?: boolean;
}

export type RowState = "open" | "done" | "ignored";

export function isIgnored(target: unknown, opts: CableOptions): boolean {
  const length = parseNumber(target);
  if (opts.ignoreNoTarget && (length === null || length <= 0)) return true; // keine Soll-Meter
  return !!opts.ignoreShort && length !== null && length < opts.minLength;
}

export const NO_SECTION = "(ohne Querschnitt)";

/** Querschnitt einer Zeile als Gruppenname (leer -> "(ohne Querschnitt)"). */
export function sectionLabel(row: Row, mapping: Mapping): string {
  const raw = mapping.cross_section ? row[mapping.cross_section] : null;
  return raw === null || raw === undefined || String(raw).trim() === "" ? NO_SECTION : String(raw).trim();
}

export const NO_ROUTE = "(ohne Ziele)";

/** Strecke eines Kabels; A -> B und B -> A sind dieselbe Strecke (wie in der Prognose). */
export function routeGroup(row: Row, mapping: Mapping): string {
  const t = (key?: string) => (key ? display(row[key]).trim() : "");
  const [a, b] = [t(mapping.target1), t(mapping.target2)].sort((x, y) => x.localeCompare(y, "de", { numeric: true }));
  if (!a && !b) return NO_ROUTE;
  return a && b ? `${a} ↔ ${b}` : a || b;
}

export type GroupBy = "section" | "route";

/** Warnung bei auffälligen Eingaben (Tippfehler), sonst null. */
export const DEVIATION_LIMIT = 0.2;
export function plausibility(target: unknown, start: unknown, end: unknown): string | null {
  const a = parseNumber(start), b = parseNumber(end);
  if (a !== null && b !== null && a === b) return "Von und Bis sind gleich";
  const length = computeLength(start, end);
  const soll = parseNumber(target);
  if (length !== null && length > 0 && soll !== null && soll > 0) {
    const deviation = (length - soll) / soll;
    if (Math.abs(deviation) > DEVIATION_LIMIT) {
      const pct = Math.round(deviation * 100);
      return `Länge ${formatNumber(length)} m statt Soll ${formatNumber(soll)} m (${pct > 0 ? "+" : ""}${pct} %)`;
    }
  }
  return null;
}

export function compareSections(a: string, b: string): number {
  const na = parseNumber(a) ?? Infinity, nb = parseNumber(b) ?? Infinity;
  return na === nb ? a.localeCompare(b) : na < nb ? -1 : 1;
}

/** Alle vorkommenden Querschnitte, numerisch sortiert. */
export function crossSections(rows: Row[], mapping: Mapping): string[] {
  return [...new Set(rows.map((r) => sectionLabel(r, mapping)))].sort(compareSections);
}

export function rowState(row: Row, mapping: Mapping, opts: CableOptions): RowState {
  if (mapping.target_length && isIgnored(row[mapping.target_length], opts)) return "ignored";
  const pulled = mapping.pulled_length ? parseNumber(row[mapping.pulled_length]) : null;
  return (pulled ?? 0) > 0 ? "done" : "open";
}

export interface GroupStats {
  label: string;
  total: number;
  done: number;
  metersTotal: number;
  metersDone: number;
}

export const percent = (part: number, whole: number) => (whole ? Math.min((100 * part) / whole, 100) : 0);

export interface Analysis {
  groups: GroupStats[];
  total: GroupStats;
  ignored: number;
}

export function mappingComplete(mapping: Mapping, columns: string[]): boolean {
  return MAPPING_FIELDS.filter((f) => f.required).every((f) => {
    const column = mapping[f.key];
    return !!column && columns.includes(column);
  });
}

export function analyze(rows: Row[], mapping: Mapping, opts: CableOptions, by: GroupBy = "section"): Analysis {
  const groups = new Map<string, GroupStats>();
  const total: GroupStats = { label: "Gesamt", total: 0, done: 0, metersTotal: 0, metersDone: 0 };
  let ignored = 0;
  for (const row of rows) {
    const state = rowState(row, mapping, opts);
    if (state === "ignored") {
      ignored += 1;
      continue;
    }
    const label = by === "route" ? routeGroup(row, mapping) : sectionLabel(row, mapping);
    let group = groups.get(label);
    if (!group) groups.set(label, (group = { label, total: 0, done: 0, metersTotal: 0, metersDone: 0 }));
    const meters = (mapping.target_length ? parseNumber(row[mapping.target_length]) : null) ?? 0;
    for (const bucket of [group, total]) {
      bucket.total += 1;
      bucket.metersTotal += meters;
      if (state === "done") {
        bucket.done += 1;
        bucket.metersDone += meters;
      }
    }
  }
  const sorted = [...groups.values()].sort((a, b) => by === "route" ? a.label.localeCompare(b.label, "de", { numeric: true }) : compareSections(a.label, b.label));
  return { groups: sorted, total, ignored };
}
