// Synchronisation: erst lokale Änderungen senden (Outbox), dann den Server-Stand inkrementell holen.
import { api } from "./api";
import { DatasetState, LocalRow, OutboxEntry, getDb } from "./db";

export interface Backend {
  key: string;
  base: string; // "/api/datasets/5" oder "/api/share/<token>"
  share: boolean;
}

export const datasetBackend = (id: number): Backend => ({ key: `ds:${id}`, base: `/api/datasets/${id}`, share: false });
export const shareBackend = (token: string): Backend => ({
  key: `share:${token}`,
  base: `/api/share/${encodeURIComponent(token)}`,
  share: true,
});

export interface Conflict {
  rowId: number;
  field: string;
  mine: unknown;
  theirs: unknown;
}

export interface SyncReport {
  pushed: number;
  conflicts: Conflict[];
  errors: string[];
}

interface ServerRow {
  id: number;
  idx: number;
  data: Record<string, unknown>;
  rev: number;
  deleted: boolean;
}

interface PushResult {
  id: number;
  status: "ok" | "conflict" | "error";
  conflicts: string[];
  error?: string;
  row?: ServerRow;
}

async function fetchMeta(b: Backend): Promise<Pick<DatasetState, "id" | "name" | "columns" | "settings" | "canEdit">> {
  if (b.share) {
    const r = await api<{ mode: string; dataset: { id: number; name: string; columns: string[]; settings: DatasetState["settings"] } }>(
      b.base,
      { quiet401: true },
    );
    return { ...r.dataset, canEdit: r.mode === "edit" };
  }
  const d = await api<{ id: number; name: string; columns: string[]; settings: DatasetState["settings"]; role: string }>(b.base);
  return { id: d.id, name: d.name, columns: d.columns, settings: d.settings, canEdit: d.role !== "viewer" };
}

export async function syncDataset(b: Backend): Promise<SyncReport> {
  const db = await getDb();
  const report: SyncReport = { pushed: 0, conflicts: [], errors: [] };
  let state = await db.get("datasets", b.key);

  // 1) lokal geänderte Einstellungen / neue Spalten übertragen (vor den Zeilen, die sie nutzen)
  if (state && !b.share && (state.pendingColumns.length || state.settingsDirty)) {
    const meta = await api<{ columns: string[]; settings: DatasetState["settings"] }>(b.base, {
      method: "PATCH",
      body: { settings: state.settings, add_columns: state.pendingColumns },
    });
    state = { ...state, columns: meta.columns, settings: meta.settings, pendingColumns: [], settingsDirty: false };
    await db.put("datasets", state);
  }

  // 2) Outbox senden
  const entries = await db.getAllFromIndex("outbox", "byDataset", b.key);
  if (entries.length) {
    const sent = new Map<number, OutboxEntry>(entries.map((e) => [e.id, e]));
    const response = await api<{ results: PushResult[] }>(`${b.base}/sync`, {
      method: "POST",
      quiet401: b.share,
      body: { ops: entries.map((e) => ({ id: e.id, base_rev: e.base_rev, base: e.base, patch: e.patch })) },
    });
    for (const result of response.results) {
      const entry = sent.get(result.id);
      if (!entry) continue;
      if (result.status === "error") report.errors.push(result.error ?? "Unbekannter Fehler");
      for (const field of result.conflicts) {
        report.conflicts.push({ rowId: result.id, field, mine: entry.patch[field], theirs: result.row?.data[field] });
      }
      if (result.status !== "error") report.pushed += 1;
      const latest = await db.get("outbox", [b.key, entry.id]);
      if (result.row && !result.row.deleted) {
        if (latest && latest.ver !== entry.ver) {
          // während der Übertragung weiter bearbeitet: auf die neue Server-Revision aufsetzen
          const base = Object.fromEntries(Object.keys(latest.patch).map((f) => [f, result.row!.data[f] ?? null]));
          await db.put("outbox", { ...latest, base_rev: result.row.rev, base });
          await db.put("rows", toLocal(b.key, result.row, latest.patch));
          continue;
        }
        await db.put("rows", toLocal(b.key, result.row));
      } else if (result.row?.deleted) {
        await db.delete("rows", [b.key, result.id]);
      }
      if (!latest || latest.ver === entry.ver) await db.delete("outbox", [b.key, entry.id]);
    }
  }

  // 3) Server-Stand holen
  const meta = await fetchMeta(b);
  state = (await db.get("datasets", b.key)) ?? undefined;
  const since = state?.seq ?? 0;
  const pulled = await api<{ seq: number; columns: string[]; rows: ServerRow[] }>(`${b.base}/rows?since=${since}`, {
    quiet401: b.share,
  });
  const pending = new Set((await db.getAllKeysFromIndex("outbox", "byDataset", b.key)).map((k) => (k as unknown as [string, number])[1]));
  const tx = db.transaction(["rows", "datasets"], "readwrite");
  for (const row of pulled.rows) {
    if (row.deleted) await tx.objectStore("rows").delete([b.key, row.id]);
    else if (!pending.has(row.id)) await tx.objectStore("rows").put(toLocal(b.key, row));
  }
  const current = (await tx.objectStore("datasets").get(b.key)) ?? undefined;
  const keepLocal = current?.settingsDirty;
  await tx.objectStore("datasets").put({
    key: b.key,
    ...meta,
    columns: mergeColumns(pulled.columns ?? meta.columns, current?.pendingColumns ?? []),
    settings: keepLocal ? current!.settings : meta.settings,
    seq: pulled.seq,
    pendingColumns: current?.pendingColumns ?? [],
    settingsDirty: keepLocal ?? false,
    lastSync: Date.now(),
  });
  await tx.done;
  return report;
}

function mergeColumns(server: string[], pending: string[]): string[] {
  return [...server, ...pending.filter((c) => !server.includes(c))];
}

function toLocal(dsKey: string, row: ServerRow, overlay: Record<string, unknown> = {}): LocalRow {
  return { dsKey, id: row.id, idx: row.idx, rev: row.rev, data: { ...row.data, ...overlay } };
}
