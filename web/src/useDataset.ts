import { useCallback, useEffect, useRef, useState } from "react";
import { ApiError, OfflineError } from "./api";
import { DatasetState, LocalRow, editRow, getDb, loadRows, pendingCount } from "./db";
import { Backend, Conflict, syncDataset } from "./sync";

const AUTO_SYNC_MS = 30_000;
const EDIT_SYNC_DELAY_MS = 1_500;

export function useDataset(backend: Backend) {
  const [state, setState] = useState<DatasetState | null>(null);
  const [rows, setRows] = useState<LocalRow[]>([]);
  const [pending, setPending] = useState(0);
  const [online, setOnline] = useState(navigator.onLine);
  const [syncing, setSyncing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [expired, setExpired] = useState(false);
  const [gone, setGone] = useState(false);
  const [conflicts, setConflicts] = useState<Conflict[]>([]);
  const [loaded, setLoaded] = useState(false);
  const busy = useRef(false);
  const timer = useRef<number | undefined>(undefined);

  const reload = useCallback(async () => {
    const db = await getDb();
    setState((await db.get("datasets", backend.key)) ?? null);
    setRows(await loadRows(backend.key));
    setPending(await pendingCount(backend.key));
    setLoaded(true);
  }, [backend.key]);

  const syncNow = useCallback(async () => {
    if (busy.current) return;
    busy.current = true;
    setSyncing(true);
    try {
      const report = await syncDataset(backend);
      if (report.conflicts.length) setConflicts((prev) => [...prev, ...report.conflicts]);
      setError(report.errors.length ? report.errors.join("; ") : null);
      setOnline(true);
      setExpired(false);
      setGone(false);
    } catch (e) {
      if (e instanceof OfflineError) setOnline(false);
      else if (e instanceof ApiError && e.status === 401) setExpired(true);
      else if (e instanceof ApiError && e.status === 404) setGone(true);
      else setError(e instanceof Error ? e.message : String(e));
    } finally {
      busy.current = false;
      setSyncing(false);
      await reload();
    }
  }, [backend, reload]);

  useEffect(() => {
    setLoaded(false);
    void reload().then(syncNow);
    const interval = window.setInterval(() => void syncNow(), AUTO_SYNC_MS);
    const goOnline = () => {
      setOnline(true);
      void syncNow();
    };
    const goOffline = () => setOnline(false);
    const visible = () => document.visibilityState === "visible" && void syncNow();
    window.addEventListener("online", goOnline);
    window.addEventListener("offline", goOffline);
    document.addEventListener("visibilitychange", visible);
    return () => {
      window.clearInterval(interval);
      window.clearTimeout(timer.current);
      window.removeEventListener("online", goOnline);
      window.removeEventListener("offline", goOffline);
      document.removeEventListener("visibilitychange", visible);
    };
  }, [reload, syncNow]);

  const scheduleSync = useCallback(() => {
    window.clearTimeout(timer.current);
    timer.current = window.setTimeout(() => void syncNow(), EDIT_SYNC_DELAY_MS);
  }, [syncNow]);

  const edit = useCallback(
    async (rowId: number, patch: Record<string, unknown>) => {
      const updated = await editRow(backend.key, rowId, patch);
      setRows((prev) => prev.map((r) => (r.id === rowId ? updated : r)));
      setPending(await pendingCount(backend.key));
      scheduleSync();
    },
    [backend.key, scheduleSync],
  );

  const patchState = useCallback(
    async (change: (s: DatasetState) => DatasetState) => {
      const db = await getDb();
      const current = await db.get("datasets", backend.key);
      if (!current) return;
      const next = change(current);
      await db.put("datasets", next);
      setState(next);
      scheduleSync();
    },
    [backend.key, scheduleSync],
  );

  const updateSettings = useCallback(
    (partial: DatasetState["settings"]) =>
      patchState((s) => ({ ...s, settings: { ...s.settings, ...partial }, settingsDirty: true })),
    [patchState],
  );

  /** Legt lokal eine neue Spalte an; sie wird mit der nächsten Synchronisation am Server ergänzt. */
  const addColumn = useCallback(
    async (name: string) => {
      const trimmed = name.trim();
      await patchState((s) =>
        s.columns.includes(trimmed)
          ? s
          : { ...s, columns: [...s.columns, trimmed], pendingColumns: [...s.pendingColumns, trimmed] },
      );
      return trimmed;
    },
    [patchState],
  );

  const keepMine = useCallback(
    async (conflict: Conflict) => {
      await edit(conflict.rowId, { [conflict.field]: conflict.mine });
      setConflicts((prev) => prev.filter((c) => c !== conflict));
    },
    [edit],
  );
  const keepTheirs = useCallback((conflict: Conflict) => setConflicts((prev) => prev.filter((c) => c !== conflict)), []);

  return {
    state, rows, pending, online, syncing, error, expired, gone, conflicts, loaded,
    syncNow, edit, updateSettings, addColumn, keepMine, keepTheirs,
  };
}
