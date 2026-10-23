import { FormEvent, useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { api, download, errorText } from "../api";
import { ProjectRef, deDay, deWhen, num, qtyText, today, useProjects, useStored } from "../planning";

interface CatalogItem { id: number; name: string; article_no: string; category: string; unit: string; note: string; image_url: string; created_by: string }
interface Req {
  id: number; project_id: number | null; project: string; catalog_id: number | null; title: string; article_no: string;
  unit: string; qty: number; kind: "bringen" | "pruefen"; due: string; note: string; status: "open" | "packed" | "done";
  requested_by: string; packed_by: string; packed_at: string | null; done_by: string; done_at: string | null; image_url: string;
}
interface Summary {
  total: number;
  by_item: { title: string; article_no: string; unit: string; count: number; qty: number }[];
  by_month: { period: string; count: number; qty: number }[];
  by_user: { user: string; count: number }[];
  by_project: { project: string; count: number }[];
}
type Tab = "bedarf" | "katalog" | "archiv";
type View = "liste" | "bilder";

/** "all" | "none" | Projekt-ID -> Abfrageparameter */
function scopeQuery(scope: string): URLSearchParams {
  const p = new URLSearchParams();
  if (scope === "none") p.set("all_projects", "false");
  else if (scope !== "all") p.set("project_id", scope);
  return p;
}

function Thumb({ url, name, big }: { url: string; name: string; big?: boolean }) {
  return url
    ? <img className={big ? "shop-img big" : "shop-img"} src={url} alt={name} loading="lazy" />
    : <div className={big ? "shop-img big empty" : "shop-img empty"} aria-hidden>{name.slice(0, 1).toUpperCase()}</div>;
}

export function ShopPage() {
  const projects = useProjects();
  const [params, setParams] = useSearchParams();
  const scope = params.get("project") ?? "all";
  const [tab, setTab] = useState<Tab>("bedarf");
  const [view, setView] = useStored<View>("shop.view", "liste");
  const [q, setQ] = useState("");
  const [error, setError] = useState("");

  const writable = (scopeId: string) =>
    scopeId === "all" || scopeId === "none" || projects.find((p) => String(p.id) === scopeId)?.role !== "viewer";

  return (
    <div className="shop">
      <h1>Einkauf &amp; Packliste</h1>
      <p className="muted">Was muss nächste Woche mit auf die Baustelle, was ist zu prüfen? Abhaken, wer es gepackt und mitgebracht hat – abgehakte Einträge landen im Archiv.</p>
      <div className="search-row">
        <select value={scope} onChange={(e) => setParams(e.target.value === "all" ? {} : { project: e.target.value })} aria-label="Projekt">
          <option value="all">Alle Projekte</option>
          <option value="none">Ohne Projekt</option>
          {projects.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}
        </select>
        <input type="search" placeholder="Suchen (Name, Artikelnummer, Notiz) …" value={q} onChange={(e) => setQ(e.target.value)} />
        <span className="segmented">
          <button className={view === "liste" ? "active" : ""} onClick={() => setView("liste")}>Liste</button>
          <button className={view === "bilder" ? "active" : ""} onClick={() => setView("bilder")}>Bilder</button>
        </span>
      </div>
      <div className="tabs">
        {([["bedarf", "Bedarf / Packliste"], ["katalog", "Katalog"], ["archiv", "Archiv & Auswertung"]] as [Tab, string][]).map(([id, label]) => (
          <button key={id} className={tab === id ? "active" : ""} onClick={() => setTab(id)}>{label}</button>
        ))}
      </div>
      {error && <p className="error">{error}</p>}
      {tab === "bedarf" && <Needs scope={scope} q={q} view={view} projects={projects} canWrite={writable(scope)} onError={setError} />}
      {tab === "katalog" && <Catalog scope={scope} q={q} view={view} canWrite={writable(scope)} onError={setError} />}
      {tab === "archiv" && <Archive scope={scope} q={q} view={view} onError={setError} />}
    </div>
  );
}

// ---- Bedarf ----

function Needs({ scope, q, view, projects, canWrite, onError }: {
  scope: string; q: string; view: View; projects: ProjectRef[]; canWrite: boolean; onError: (e: string) => void;
}) {
  const [rows, setRows] = useState<Req[] | null>(null);
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    try {
      const p = scopeQuery(scope);
      p.set("state", "open");
      if (q.trim()) p.set("q", q.trim());
      setRows(await api<Req[]>(`/api/shop/requests?${p}`));
      onError("");
    } catch (e) { onError(errorText(e)); }
  }, [scope, q, onError]);
  useEffect(() => {
    const t = setTimeout(() => void load(), q ? 250 : 0);
    return () => clearTimeout(t);
  }, [load, q]);
  useEffect(() => { // andere Personen haken parallel ab
    const t = setInterval(() => { if (!document.hidden) void load(); }, 15000);
    return () => clearInterval(t);
  }, [load]);

  const act = async (fn: () => Promise<unknown>) => {
    setBusy(true);
    try { await fn(); await load(); } catch (e) { onError(errorText(e)); } finally { setBusy(false); }
  };
  const flag = (r: Req, what: "pack" | "done", value: boolean) =>
    act(() => api(`/api/shop/requests/${r.id}/${what}`, { method: "POST", body: { value } }));
  const remove = (r: Req) => confirm(`„${r.title}“ von der Liste nehmen?`) && act(() => api(`/api/shop/requests/${r.id}`, { method: "DELETE" }));
  const edit = (r: Req) => {
    const text = prompt(`Menge für „${r.title}“ (${r.unit})`, qtyText(r.qty));
    if (text === null) return;
    const qty = num(text);
    if (!(qty > 0)) { onError("Menge muss größer als 0 sein."); return; }
    void act(() => api(`/api/shop/requests/${r.id}`, { method: "PATCH", body: { qty } }));
  };

  const groups = useMemo(() => {
    const map = new Map<string, Req[]>();
    for (const r of rows ?? []) {
      const key = r.project || "Ohne Projekt";
      map.set(key, [...(map.get(key) ?? []), r]);
    }
    return [...map.entries()];
  }, [rows]);

  const open = (rows ?? []).filter((r) => r.status === "open").length;
  const packed = (rows ?? []).length - open;

  return (
    <>
      {canWrite && <AddRequest scope={scope} projects={projects} onAdded={load} onError={onError} />}
      <div className="stat-line">
        <span className="chip">{open} offen</span><span className="chip ok">{packed} gepackt</span>
      </div>
      {rows === null && <p className="muted"><span className="spinner" /> Lade …</p>}
      {rows?.length === 0 && <p className="muted card pad">Nichts auf der Liste. Oben etwas hinzufügen oder im Katalog „Zur Liste“ wählen.</p>}
      {groups.map(([name, list]) => (
        <section className="card" key={name}>
          {(scope === "all" || groups.length > 1) && <h2>{name}</h2>}
          <ul className={view === "bilder" ? "shop-grid" : "shop-list"}>
            {list.map((r) => (
              <li key={r.id} className={`shop-row ${r.status}`}>
                <Thumb url={r.image_url} name={r.title} big={view === "bilder"} />
                <div className="shop-main">
                  <b>{r.title}</b>
                  <div className="stat-line">
                    <span className="chip">{qtyText(r.qty)} {r.unit}</span>
                    {r.article_no && <span className="chip">Art.-Nr. {r.article_no}</span>}
                    <span className={`chip ${r.kind === "pruefen" ? "warn" : ""}`}>{r.kind === "pruefen" ? "prüfen" : "mitbringen"}</span>
                    {r.due && <span className="chip">bis {deDay(r.due)}</span>}
                  </div>
                  {r.note && <div className="muted">{r.note}</div>}
                  <div className="muted small">von {r.requested_by}</div>
                </div>
                <div className="shop-checks">
                  <label className="check">
                    <input type="checkbox" checked={r.status === "packed"} disabled={!canWrite || busy} onChange={(e) => void flag(r, "pack", e.target.checked)} />
                    gepackt
                    {r.packed_at && <small className="muted">{r.packed_by}, {deWhen(r.packed_at)}</small>}
                  </label>
                  <label className="check">
                    <input type="checkbox" checked={false} disabled={!canWrite || busy} onChange={(e) => void flag(r, "done", e.target.checked)} />
                    erledigt / mitgebracht
                  </label>
                  {canWrite && <span className="actions"><button onClick={() => edit(r)}>Menge</button><button className="danger" onClick={() => remove(r)}>Entfernen</button></span>}
                </div>
              </li>
            ))}
          </ul>
        </section>
      ))}
    </>
  );
}

function AddRequest({ scope, projects, onAdded, onError }: {
  scope: string; projects: ProjectRef[]; onAdded: () => Promise<void>; onError: (e: string) => void;
}) {
  const [text, setText] = useState("");
  const [picked, setPicked] = useState<CatalogItem | null>(null);
  const [hits, setHits] = useState<CatalogItem[]>([]);
  const [qty, setQty] = useState("1");
  const [kind, setKind] = useState("bringen");
  const [target, setTarget] = useState(scope === "all" || scope === "none" ? "none" : scope);
  const [due, setDue] = useState("");
  const [note, setNote] = useState("");
  const [toCatalog, setToCatalog] = useState(true);
  const [busy, setBusy] = useState(false);
  const box = useRef<HTMLInputElement>(null);

  useEffect(() => { setTarget(scope === "all" || scope === "none" ? "none" : scope); }, [scope]);
  useEffect(() => {
    if (picked || text.trim().length < 1) { setHits([]); return; }
    const t = setTimeout(() => {
      api<CatalogItem[]>(`/api/shop/catalog?q=${encodeURIComponent(text.trim())}`).then((l) => setHits(l.slice(0, 6))).catch(() => setHits([]));
    }, 200);
    return () => clearTimeout(t);
  }, [text, picked]);

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    const amount = num(qty);
    if (!(amount > 0)) { onError("Menge muss größer als 0 sein."); return; }
    setBusy(true);
    try {
      let catalogId = picked?.id ?? null;
      if (!picked) {
        if (!text.trim()) { onError("Bitte einen Artikel wählen oder eine Bezeichnung eintippen."); return; }
        if (toCatalog) catalogId = (await api<CatalogItem>("/api/shop/catalog", { method: "POST", body: { name: text.trim() } })).id;
      }
      await api("/api/shop/requests", { method: "POST", body: {
        catalog_id: catalogId, title: picked ? "" : text.trim(), qty: amount, kind, due,
        project_id: target === "none" ? null : Number(target), note,
      } });
      setText(""); setPicked(null); setQty("1"); setNote(""); setDue("");
      onError("");
      await onAdded();
      box.current?.focus();
    } catch (err) { onError(errorText(err)); } finally { setBusy(false); }
  };

  return (
    <form className="card add-request" onSubmit={(e) => void submit(e)}>
      <h2>Auf die Liste setzen</h2>
      <div className="inline-form">
        <div className="typeahead">
          <input ref={box} className="wide" value={picked ? picked.name : text} placeholder="Artikel suchen oder neu eintippen …"
                 onChange={(e) => { setPicked(null); setText(e.target.value); }} aria-label="Artikel" />
          {hits.length > 0 && (
            <ul className="hits">
              {hits.map((h) => (
                <li key={h.id}><button type="button" onClick={() => { setPicked(h); setHits([]); }}>
                  <Thumb url={h.image_url} name={h.name} /> <span><b>{h.name}</b>{h.article_no && <small className="muted"> · {h.article_no}</small>}</span>
                </button></li>
              ))}
            </ul>
          )}
        </div>
        <input className="narrow" inputMode="decimal" value={qty} onChange={(e) => setQty(e.target.value)} aria-label="Menge" />
        <span className="muted">{picked?.unit ?? "Stk"}</span>
        <select value={kind} onChange={(e) => setKind(e.target.value)} aria-label="Art">
          <option value="bringen">mitbringen</option><option value="pruefen">prüfen</option>
        </select>
        <select value={target} onChange={(e) => setTarget(e.target.value)} aria-label="Für Projekt">
          <option value="none">Ohne Projekt</option>
          {projects.filter((p) => p.role !== "viewer").map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}
        </select>
        <input type="date" value={due} min={today()} onChange={(e) => setDue(e.target.value)} aria-label="Bis wann" title="Bis wann (optional)" />
        <input value={note} onChange={(e) => setNote(e.target.value)} placeholder="Notiz (optional)" maxLength={500} />
        <button className="primary" disabled={busy}>Hinzufügen</button>
      </div>
      {!picked && text.trim() && hits.length === 0 && (
        <label className="check"><input type="checkbox" checked={toCatalog} onChange={(e) => setToCatalog(e.target.checked)} /> Neu im Katalog anlegen, damit ihn alle wiederfinden</label>
      )}
    </form>
  );
}

// ---- Katalog ----

function Catalog({ scope, q, view, canWrite, onError }: {
  scope: string; q: string; view: View; canWrite: boolean; onError: (e: string) => void;
}) {
  const [items, setItems] = useState<CatalogItem[] | null>(null);
  const [categories, setCategories] = useState<string[]>([]);
  const [category, setCategory] = useState("");
  const [editing, setEditing] = useState<number | "new" | null>(null);

  const load = useCallback(async () => {
    try {
      const p = new URLSearchParams();
      if (q.trim()) p.set("q", q.trim());
      if (category) p.set("category", category);
      const [list, cats] = await Promise.all([api<CatalogItem[]>(`/api/shop/catalog?${p}`), api<string[]>("/api/shop/categories")]);
      setItems(list); setCategories(cats); onError("");
    } catch (e) { onError(errorText(e)); }
  }, [q, category, onError]);
  useEffect(() => {
    const t = setTimeout(() => void load(), q ? 250 : 0);
    return () => clearTimeout(t);
  }, [load, q]);

  const target = scope === "all" || scope === "none" ? null : Number(scope);
  const addToList = async (item: CatalogItem, qty: number) => {
    try {
      await api("/api/shop/requests", { method: "POST", body: { catalog_id: item.id, qty, project_id: target } });
      onError("");
      alert(`„${item.name}“ steht jetzt auf der Liste${target ? "" : " (ohne Projekt)"}.`);
    } catch (e) { onError(errorText(e)); }
  };
  const remove = async (item: CatalogItem) => {
    if (!confirm(`„${item.name}“ aus dem Katalog löschen? Bereits abgehakte Einträge im Archiv bleiben erhalten.`)) return;
    try { await api(`/api/shop/catalog/${item.id}`, { method: "DELETE" }); await load(); } catch (e) { onError(errorText(e)); }
  };
  const picture = async (item: CatalogItem, file: File | undefined) => {
    if (!file) return;
    const form = new FormData();
    form.append("file", file);
    try { await api(`/api/shop/catalog/${item.id}/image`, { method: "PUT", form }); await load(); } catch (e) { onError(errorText(e)); }
  };

  return (
    <>
      <div className="search-row">
        <select value={category} onChange={(e) => setCategory(e.target.value)} aria-label="Kategorie">
          <option value="">Alle Kategorien</option>
          {categories.map((c) => <option key={c}>{c}</option>)}
        </select>
        {canWrite && <button className="primary" onClick={() => setEditing("new")}>Neuer Artikel</button>}
        <span className="muted">{items?.length ?? 0} Artikel · „Zur Liste“ {target ? "für das gewählte Projekt" : "ohne Projekt (oben ein Projekt wählen)"}</span>
      </div>
      {editing === "new" && <ItemForm onDone={() => { setEditing(null); void load(); }} onCancel={() => setEditing(null)} onError={onError} />}
      {items === null && <p className="muted"><span className="spinner" /> Lade …</p>}
      {items?.length === 0 && <p className="muted card pad">Keine Artikel gefunden. Mit „Neuer Artikel“ den Katalog füllen – er gilt für alle Projekte.</p>}
      <ul className={view === "bilder" ? "shop-grid" : "shop-list card"}>
        {items?.map((item) => (
          <li key={item.id} className="shop-row">
            {editing === item.id ? (
              <ItemForm item={item} onDone={() => { setEditing(null); void load(); }} onCancel={() => setEditing(null)} onError={onError} />
            ) : (
              <>
                <label className="pic" title={canWrite ? "Bild ändern" : ""}>
                  <Thumb url={item.image_url} name={item.name} big={view === "bilder"} />
                  {canWrite && <input type="file" accept="image/png,image/jpeg,image/gif,image/webp" hidden onChange={(e) => void picture(item, e.target.files?.[0])} />}
                </label>
                <div className="shop-main">
                  <b>{item.name}</b>
                  <div className="stat-line">
                    {item.article_no && <span className="chip">Art.-Nr. {item.article_no}</span>}
                    {item.category && <span className="chip">{item.category}</span>}
                    <span className="chip">{item.unit}</span>
                  </div>
                  {item.note && <div className="muted">{item.note}</div>}
                </div>
                <div className="shop-checks">
                  {canWrite && <AddButton item={item} onAdd={addToList} />}
                  {canWrite && <span className="actions"><button onClick={() => setEditing(item.id)}>Bearbeiten</button><button className="danger" onClick={() => void remove(item)}>Löschen</button></span>}
                </div>
              </>
            )}
          </li>
        ))}
      </ul>
    </>
  );
}

function AddButton({ item, onAdd }: { item: CatalogItem; onAdd: (i: CatalogItem, qty: number) => Promise<void> }) {
  const [qty, setQty] = useState("1");
  return (
    <span className="inline-form">
      <input className="narrow" inputMode="decimal" value={qty} onChange={(e) => setQty(e.target.value)} aria-label={`Menge ${item.name}`} />
      <button className="primary" onClick={() => { const n = num(qty); if (n > 0) void onAdd(item, n); }}>Zur Liste</button>
    </span>
  );
}

function ItemForm({ item, onDone, onCancel, onError }: { item?: CatalogItem; onDone: () => void; onCancel: () => void; onError: (e: string) => void }) {
  const [f, setF] = useState({ name: item?.name ?? "", article_no: item?.article_no ?? "", category: item?.category ?? "", unit: item?.unit ?? "Stk", note: item?.note ?? "" });
  const set = (k: keyof typeof f) => (e: { target: { value: string } }) => setF({ ...f, [k]: e.target.value });
  const submit = async (e: FormEvent) => {
    e.preventDefault();
    try {
      if (item) await api(`/api/shop/catalog/${item.id}`, { method: "PATCH", body: f });
      else await api("/api/shop/catalog", { method: "POST", body: f });
      onError("");
      onDone();
    } catch (err) { onError(errorText(err)); }
  };
  return (
    <form className="card item-form" onSubmit={(e) => void submit(e)}>
      <div className="inline-form">
        <input className="wide" required placeholder="Bezeichnung" value={f.name} onChange={set("name")} maxLength={200} />
        <input placeholder="Artikelnummer" value={f.article_no} onChange={set("article_no")} maxLength={100} />
        <input placeholder="Kategorie" value={f.category} onChange={set("category")} maxLength={100} />
        <input className="narrow" placeholder="Einheit" value={f.unit} onChange={set("unit")} maxLength={30} />
        <input placeholder="Notiz (z. B. Größe, Lieferant)" value={f.note} onChange={set("note")} maxLength={500} />
        <button className="primary">Speichern</button><button type="button" onClick={onCancel}>Abbrechen</button>
      </div>
      {!item && <p className="muted small">Ein Bild kannst du danach durch Klick auf das Bildfeld hinzufügen (PNG, JPEG, GIF, WebP bis 3 MB).</p>}
    </form>
  );
}

// ---- Archiv ----

function Archive({ scope, q, view, onError }: { scope: string; q: string; view: View; onError: (e: string) => void }) {
  const [from, setFrom] = useState("");
  const [to, setTo] = useState("");
  const [rows, setRows] = useState<Req[] | null>(null);
  const [sum, setSum] = useState<Summary | null>(null);

  const query = useCallback(() => {
    const p = scopeQuery(scope);
    if (from) p.set("date_from", from);
    if (to) p.set("date_to", to);
    return p;
  }, [scope, from, to]);

  useEffect(() => {
    const t = setTimeout(async () => {
      try {
        const p = query();
        const list = new URLSearchParams(p);
        list.set("state", "done");
        if (q.trim()) list.set("q", q.trim());
        const [r, s] = await Promise.all([api<Req[]>(`/api/shop/requests?${list}`), api<Summary>(`/api/shop/summary?${p}`)]);
        setRows(r); setSum(s); onError("");
      } catch (e) { onError(errorText(e)); }
    }, q ? 250 : 0);
    return () => clearTimeout(t);
  }, [query, q, onError]);

  const reopen = async (r: Req) => {
    try {
      await api(`/api/shop/requests/${r.id}/done`, { method: "POST", body: { value: false } });
      setRows((rows ?? []).filter((x) => x.id !== r.id));
    } catch (e) { onError(errorText(e)); }
  };

  return (
    <>
      <div className="search-row">
        <label>von <input type="date" value={from} onChange={(e) => setFrom(e.target.value)} /></label>
        <label>bis <input type="date" value={to} onChange={(e) => setTo(e.target.value)} /></label>
        <button onClick={() => void download(`/api/shop/export?${query()}`, "einkauf.xlsx").catch((e) => onError(errorText(e)))}>Als Excel exportieren</button>
      </div>
      {sum && (
        <section className="card">
          <h2>Auswertung ({sum.total} abgehakt)</h2>
          {sum.total === 0 ? <p className="muted">Im gewählten Bereich ist noch nichts abgehakt.</p> : (
            <div className="stats-grid">
              <div><h3>Häufigste Artikel</h3><table className="analysis"><thead><tr><th>Artikel</th><th>Mal</th><th>Menge</th></tr></thead><tbody>
                {sum.by_item.slice(0, 10).map((i) => <tr key={i.title + i.article_no}><td>{i.title}{i.article_no && <small className="muted"> · {i.article_no}</small>}</td><td>{i.count}</td><td>{qtyText(i.qty)} {i.unit}</td></tr>)}
              </tbody></table></div>
              <div><h3>Je Monat</h3><table className="analysis"><thead><tr><th>Monat</th><th>Einträge</th></tr></thead><tbody>
                {sum.by_month.map((m) => <tr key={m.period}><td>{m.period}</td><td>{m.count}</td></tr>)}
              </tbody></table></div>
              <div><h3>Wer hat abgehakt</h3><table className="analysis"><thead><tr><th>Person</th><th>Einträge</th></tr></thead><tbody>
                {sum.by_user.map((u) => <tr key={u.user}><td>{u.user}</td><td>{u.count}</td></tr>)}
              </tbody></table></div>
              <div><h3>Je Projekt</h3><table className="analysis"><thead><tr><th>Projekt</th><th>Einträge</th></tr></thead><tbody>
                {sum.by_project.map((p) => <tr key={p.project}><td>{p.project}</td><td>{p.count}</td></tr>)}
              </tbody></table></div>
            </div>
          )}
        </section>
      )}
      <section className="card">
        <h2>Archiv: auf der Baustelle / mitgebracht</h2>
        {rows === null && <p className="muted"><span className="spinner" /> Lade …</p>}
        <ul className={view === "bilder" ? "shop-grid" : "shop-list"}>
          {rows?.map((r) => (
            <li key={r.id} className="shop-row done">
              <Thumb url={r.image_url} name={r.title} big={view === "bilder"} />
              <div className="shop-main">
                <b>{r.title}</b>
                <div className="stat-line">
                  <span className="chip">{qtyText(r.qty)} {r.unit}</span>
                  {r.article_no && <span className="chip">Art.-Nr. {r.article_no}</span>}
                  {r.project && <span className="chip">{r.project}</span>}
                  <span className="chip">{r.kind === "pruefen" ? "geprüft" : "mitgebracht"}</span>
                </div>
                <div className="muted small">
                  angefordert von {r.requested_by}{r.packed_at && <> · gepackt von {r.packed_by} ({deWhen(r.packed_at)})</>}
                  <br />abgehakt von <b>{r.done_by}</b> am {deWhen(r.done_at)}
                </div>
              </div>
              <div className="shop-checks"><button onClick={() => void reopen(r)}>Wieder auf die Liste</button></div>
            </li>
          ))}
        </ul>
        {rows?.length === 0 && <p className="muted">Noch nichts im Archiv.</p>}
      </section>
    </>
  );
}
