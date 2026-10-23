/** Gemeinsame Hilfen für Einkauf, Whiteboard, Tagesbericht und Kalender. */
import { useEffect, useState } from "react";
import { api } from "./api";

export interface ProjectRef { id: number; name: string; role: string }

/** Eigene Projekte (für Auswahlfelder). */
export function useProjects(): ProjectRef[] {
  const [list, setList] = useState<ProjectRef[]>([]);
  useEffect(() => {
    api<ProjectRef[]>("/api/projects").then(setList).catch(() => setList([]));
  }, []);
  return list;
}

export const pad2 = (n: number) => String(n).padStart(2, "0");
export const isoDay = (d: Date) => `${d.getFullYear()}-${pad2(d.getMonth() + 1)}-${pad2(d.getDate())}`;
export const today = () => isoDay(new Date());
export const parseDay = (s: string) => new Date(`${s}T00:00:00`);
export const addDays = (s: string, n: number) => { const d = parseDay(s); d.setDate(d.getDate() + n); return isoDay(d); };
export const deDay = (s: string) => (s ? s.split("-").reverse().join(".") : "");
export const deWhen = (iso: string | null) =>
  iso ? new Date(iso).toLocaleString("de-DE", { dateStyle: "short", timeStyle: "short" }) : "";

/** Wert aus localStorage mit Rückfall (Speicher kann gesperrt sein). */
export function useStored<T extends string>(key: string, fallback: T): [T, (v: T) => void] {
  const [value, setValue] = useState<T>(() => {
    try { return (localStorage.getItem(key) as T | null) ?? fallback; } catch { return fallback; }
  });
  const set = (v: T) => {
    setValue(v);
    try { localStorage.setItem(key, v); } catch { /* ignorieren */ }
  };
  return [value, set];
}

/** Ergebnis von Hand umrechnen: "2,5" -> 2.5 (deutsche Eingabe). */
export const num = (s: string): number => Number(s.replace(",", "."));
export const qtyText = (n: number) => String(Math.round(n * 100) / 100).replace(".", ",");

export const PERIOD_LABEL = (period: string): string => {
  if (/^\d{4}$/.test(period)) return period;
  if (/^\d{4}-\d{2}$/.test(period)) {
    return new Date(`${period}-01T00:00:00`).toLocaleDateString("de-DE", { month: "long", year: "numeric" });
  }
  if (/^\d{4}-W\d{2}$/.test(period)) return `KW ${period.slice(-2)} / ${period.slice(0, 4)}`;
  return deDay(period);
};
