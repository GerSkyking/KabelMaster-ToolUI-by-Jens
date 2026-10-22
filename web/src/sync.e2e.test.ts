// Integrationstest des Client-Sync gegen einen laufenden Server:
//   WT_E2E_URL=http://127.0.0.1:8000 WT_E2E_USER=admin WT_E2E_PASS=... npx vitest run src/sync.e2e.test.ts
import "fake-indexeddb/auto";
import { beforeAll, describe, expect, it } from "vitest";
import { editRow, getDb, loadRows, pendingCount } from "./db";
import { datasetBackend, syncDataset } from "./sync";

const base = process.env.WT_E2E_URL;
const suite = base ? describe : describe.skip;

suite("sync gegen echten Server", () => {
  let cookie = "";
  let datasetId = 0;
  const realFetch = globalThis.fetch;

  beforeAll(async () => {
    globalThis.fetch = ((input: RequestInfo | URL, init: RequestInit = {}) =>
      realFetch(`${base}${String(input)}`, { ...init, headers: { ...(init.headers as object), Cookie: cookie } })) as typeof fetch;
    const login = await realFetch(`${base}/api/auth/login`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ username: process.env.WT_E2E_USER, password: process.env.WT_E2E_PASS }),
    });
    expect(login.status).toBe(200);
    cookie = (login.headers.get("set-cookie") ?? "").split(";")[0];
    const post = (path: string, body: unknown) =>
      realFetch(`${base}${path}`, { method: "POST", headers: { "Content-Type": "application/json", Cookie: cookie }, body: JSON.stringify(body) });
    const project = await (await post("/api/projects", { name: `e2e-${Date.now()}` })).json();
    const form = new FormData();
    form.append("file", new Blob([Buffer.from(await (await import("node:fs/promises")).readFile(process.env.WT_E2E_XLSX!))]), "liste.xlsx");
    await realFetch(`${base}/api/projects/${project.id}/files`, { method: "POST", headers: { Cookie: cookie }, body: form });
    datasetId = (await (await post(`/api/projects/${project.id}/datasets`, { file: "liste.xlsx" })).json()).id;
  });

  it("lädt, bearbeitet offline und überträgt später", async () => {
    const b = datasetBackend(datasetId);
    await syncDataset(b);
    const rows = await loadRows(b.key);
    expect(rows.length).toBeGreaterThan(0);

    await editRow(b.key, rows[0].id, { Von: 100, Bis: 112.5, Ist: 12.5 });
    expect(await pendingCount(b.key)).toBe(1);
    const report = await syncDataset(b);
    expect(report.pushed).toBe(1);
    expect(await pendingCount(b.key)).toBe(0);
    const state = await (await getDb()).get("datasets", b.key);
    expect(state?.seq).toBeGreaterThan(0);
    expect((await loadRows(b.key))[0].data.Ist).toBe(12.5);
  });

  it("meldet Feld-Konflikte und übernimmt andere Felder", async () => {
    const b = datasetBackend(datasetId);
    const [row] = await loadRows(b.key);
    // Fremde Änderung direkt am Server
    await realFetch(`${base}/api/datasets/${datasetId}/sync`, {
      method: "POST", headers: { "Content-Type": "application/json", Cookie: cookie },
      body: JSON.stringify({ ops: [{ id: row.id, base_rev: row.rev, base: { Von: 100 }, patch: { Von: 7 } }] }),
    });
    // Lokal (veraltete Revision) Von und Datum ändern
    await editRow(b.key, row.id, { Von: 55, Datum: "21.10.26" });
    const report = await syncDataset(b);
    expect(report.conflicts).toEqual([{ rowId: row.id, field: "Von", mine: 55, theirs: 7 }]);
    const merged = (await loadRows(b.key))[0];
    expect(merged.data.Von).toBe(7);
    expect(merged.data.Datum).toBe("21.10.26");
  });
});
