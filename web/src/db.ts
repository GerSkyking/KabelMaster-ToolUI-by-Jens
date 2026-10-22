// Lokaler Speicher (IndexedDB): Datensätze, Zeilen und die Warteschlange noch nicht übertragener Änderungen.
import { DBSchema, IDBPDatabase, openDB } from "idb";
import type { Mapping } from "./cable";

export interface DatasetState {
  key: string; // "ds:<id>" oder "share:<token>"
  id: number;
  name: string;
  columns: string[];
  settings: { mapping?: Mapping; ignore_short?: boolean; min_length?: number; auto_date?: boolean };
  canEdit: boolean;
  seq: number; // bis hierhin ist der Server-Stand lokal vorhanden
  pendingColumns: string[];
  settingsDirty: boolean;
  lastSync: number | null;
}

export interface LocalRow {
  dsKey: string;
  id: number;
  idx: number;
  rev: number;
  data: Record<string, unknown>;
}

export interface OutboxEntry {
  dsKey: string;
  id: number;
  base_rev: number;
  base: Record<string, unknown>;
  patch: Record<string, unknown>;
  ver: number; // zählt Änderungen, damit Edits während einer laufenden Synchronisation nicht verloren gehen
}

interface Schema extends DBSchema {
  datasets: { key: string; value: DatasetState };
  rows: { key: [string, number]; value: LocalRow; indexes: { byDataset: string } };
  outbox: { key: [string, number]; value: OutboxEntry; indexes: { byDataset: string } };
  kv: { key: string; value: unknown };
}

let dbPromise: Promise<IDBPDatabase<Schema>> | null = null;

export function getDb(): Promise<IDBPDatabase<Schema>> {
  dbPromise ??= openDB<Schema>("wt-listentool", 1, {
    upgrade(db) {
      db.createObjectStore("datasets", { keyPath: "key" });
      db.createObjectStore("rows", { keyPath: ["dsKey", "id"] }).createIndex("byDataset", "dsKey");
      db.createObjectStore("outbox", { keyPath: ["dsKey", "id"] }).createIndex("byDataset", "dsKey");
      db.createObjectStore("kv");
    },
  });
  return dbPromise;
}

export async function kvGet<T>(key: string): Promise<T | undefined> {
  return (await (await getDb()).get("kv", key)) as T | undefined;
}

export async function kvSet(key: string, value: unknown): Promise<void> {
  await (await getDb()).put("kv", value, key);
}

export async function loadRows(dsKey: string): Promise<LocalRow[]> {
  const rows = await (await getDb()).getAllFromIndex("rows", "byDataset", dsKey);
  return rows.sort((a, b) => a.idx - b.idx || a.id - b.id);
}

export async function pendingCount(dsKey: string): Promise<number> {
  return (await getDb()).countFromIndex("outbox", "byDataset", dsKey);
}

/** Lokale Änderung an einer Zeile: sofort sichtbar und für die nächste Synchronisation vorgemerkt. */
export async function editRow(dsKey: string, rowId: number, patch: Record<string, unknown>): Promise<LocalRow> {
  const db = await getDb();
  const tx = db.transaction(["rows", "outbox"], "readwrite");
  const row = await tx.objectStore("rows").get([dsKey, rowId]);
  if (!row) throw new Error("Zeile nicht gefunden");
  const entry: OutboxEntry =
    (await tx.objectStore("outbox").get([dsKey, rowId])) ??
    { dsKey, id: rowId, base_rev: row.rev, base: {}, patch: {}, ver: 0 };
  for (const [field, value] of Object.entries(patch)) {
    if (!(field in entry.base)) entry.base[field] = row.data[field] ?? null; // Wert vor der ersten Änderung
    entry.patch[field] = value;
  }
  entry.ver += 1;
  const updated: LocalRow = { ...row, data: { ...row.data, ...patch } };
  await tx.objectStore("rows").put(updated);
  await tx.objectStore("outbox").put(entry);
  await tx.done;
  return updated;
}
