import { FormEvent, useEffect, useState } from "react";
import { api } from "../api";
import { useAuth } from "../auth";

interface Key { id: number; name: string; prefix: string; created_at: string; last_used_at: string | null; expires_at: string | null; revoked: boolean }

export function AccountPage() {
  const { user } = useAuth();
  const [keys, setKeys] = useState<Key[]>([]);
  const [name, setName] = useState("");
  const [days, setDays] = useState<string>("");
  const [fresh, setFresh] = useState("");
  const [current, setCurrent] = useState("");
  const [next, setNext] = useState("");
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");

  const load = async () => setKeys(await api<Key[]>("/api/api-keys"));
  useEffect(() => void load().catch(() => undefined), []);

  const fail = (e: unknown) => setError(e instanceof Error ? e.message : String(e));

  const createKey = async (e: FormEvent) => {
    e.preventDefault();
    setError("");
    try {
      const r = await api<{ key: string }>("/api/api-keys", { method: "POST", body: { name, days: days ? Number(days) : null } });
      setFresh(r.key);
      setName("");
      await load();
    } catch (err) { fail(err); }
  };

  const changePassword = async (e: FormEvent) => {
    e.preventDefault();
    setError("");
    setMessage("");
    try {
      await api("/api/auth/password", { method: "POST", body: { current_password: current, new_password: next } });
      setMessage("Passwort geändert.");
      setCurrent("");
      setNext("");
    } catch (err) { fail(err); }
  };

  return (
    <div>
      <h1>Konto</h1>
      <p>{user?.display_name} ({user?.username}) · {user?.provider} · {user?.role}</p>
      {message && <p className="ok">{message}</p>}
      {error && <p className="error">{error}</p>}

      <section className="card">
        <h2>API-Keys (Windows-App / Skripte)</h2>
        <p className="muted">Ein Key gibt dieselben Rechte wie dein Konto. Senden als Header <code>X-API-Key</code>. Der Schlüssel wird nur einmal angezeigt.</p>
        <form onSubmit={createKey} className="inline-form">
          <input placeholder="Name (z. B. Büro-PC)" value={name} onChange={(e) => setName(e.target.value)} required />
          <input type="number" min={1} placeholder="Gültig (Tage, leer = unbegrenzt)" value={days} onChange={(e) => setDays(e.target.value)} />
          <button className="primary">Key erstellen</button>
        </form>
        {fresh && <p className="ok">Neuer Key: <input readOnly className="wide" value={fresh} onFocus={(e) => e.target.select()} /> <button onClick={() => void navigator.clipboard?.writeText(fresh)}>Kopieren</button></p>}
        <table className="data">
          <thead><tr><th>Name</th><th>Beginnt mit</th><th>Zuletzt genutzt</th><th>Läuft ab</th><th /></tr></thead>
          <tbody>
            {keys.map((k) => (
              <tr key={k.id} className={k.revoked ? "st-ignored" : ""}>
                <td>{k.name}</td><td><code>{k.prefix}…</code></td>
                <td>{k.last_used_at ? new Date(k.last_used_at).toLocaleString("de-DE") : "nie"}</td>
                <td>{k.expires_at ? new Date(k.expires_at).toLocaleDateString("de-DE") : "–"}</td>
                <td>{k.revoked ? "widerrufen" : <button className="danger" onClick={async () => { await api(`/api/api-keys/${k.id}`, { method: "DELETE" }); await load(); }}>Widerrufen</button>}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </section>

      {user?.provider === "local" && (
        <section className="card">
          <h2>Passwort ändern</h2>
          <form onSubmit={changePassword} className="inline-form">
            <input type="password" placeholder="Aktuelles Passwort" autoComplete="current-password" value={current} onChange={(e) => setCurrent(e.target.value)} required />
            <input type="password" placeholder="Neues Passwort (min. 10 Zeichen)" autoComplete="new-password" minLength={10} value={next} onChange={(e) => setNext(e.target.value)} required />
            <button>Ändern</button>
          </form>
        </section>
      )}
    </div>
  );
}
