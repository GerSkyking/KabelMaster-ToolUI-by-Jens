// Alle Vorlagen im Überblick: Vorlagen/<Benutzer>/<Name>. Alle sehen sie, ändern darf nur der Besitzer (oder Admin).
import { useCallback, useEffect, useState } from "react";
import { api, errorText } from "../api";

interface TemplateInfo { id: number; name: string; tab_id: string; owner: string; path: string; editable: boolean; updated_at: string }
const TAB: Record<string, string> = {
  single_search: "Einzelsuche", batch_search: "Stapelsuche", highlight: "Farbmarkierung", kmk: "KMK", cabinet: "Schrank-Erkennung", cable: "Kabelzug",
};

export function TemplatesPage() {
  const [items, setItems] = useState<TemplateInfo[]>([]);
  const [error, setError] = useState("");
  const load = useCallback(async () => {
    try {
      setItems(await api<TemplateInfo[]>("/api/templates"));
    } catch (e) {
      setError(errorText(e));
    }
  }, []);
  useEffect(() => void load(), [load]);
  const owners = [...new Set(items.map((t) => t.owner))];

  return (
    <div>
      <h1>Vorlagen</h1>
      <p className="muted">Vorlagen liegen zentral unter <code>Vorlagen/&lt;Benutzer&gt;/&lt;Name&gt;</code>. Alle sehen und nutzen sie; ändern oder löschen dürfen nur der Besitzer und Administratoren. Gespeichert wird direkt im jeweiligen Reiter.</p>
      {error && <p className="error">{error}</p>}
      {owners.map((owner) => (
        <section className="card" key={owner}>
          <h2>Vorlagen/{owner}</h2>
          <ul className="plain">
            {items.filter((t) => t.owner === owner).map((t) => (
              <li key={t.id}>
                {t.name} <span className="chip">{TAB[t.tab_id] ?? t.tab_id}</span> <span className="muted">{new Date(t.updated_at).toLocaleDateString("de-DE")}</span>
                {t.editable && <button className="danger" onClick={async () => {
                  if (!confirm(`„${t.path}“ löschen?`)) return;
                  try { await api(`/api/templates/${t.id}`, { method: "DELETE" }); await load(); } catch (e) { setError(errorText(e)); }
                }}>Löschen</button>}
              </li>
            ))}
          </ul>
        </section>
      ))}
      {!items.length && <p className="muted">Noch keine Vorlagen.</p>}
    </div>
  );
}
