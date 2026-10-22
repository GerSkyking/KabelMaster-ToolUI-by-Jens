import { FormEvent, useCallback, useEffect, useState } from "react";
import { Navigate } from "react-router-dom";
import { api } from "../api";
import { useAuth } from "../auth";
import { BackupsPanel } from "./BackupsPanel";

interface AdminUser { id: number; username: string; email: string; provider: string; role: string; is_active: boolean; last_login_at: string | null }
interface AuditEntry { id: number; ts: string; username: string; action: string; target: string; ip: string; detail: Record<string, unknown> }

export function AdminPage() {
  const { user } = useAuth();
  const [users, setUsers] = useState<AdminUser[]>([]);
  const [audit, setAudit] = useState<AuditEntry[]>([]);
  const [form, setForm] = useState({ username: "", password: "", role: "user" });
  const [error, setError] = useState("");

  const load = useCallback(async () => {
    try {
      setUsers(await api<AdminUser[]>("/api/admin/users"));
      setAudit(await api<AuditEntry[]>("/api/admin/audit?limit=100"));
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  }, []);
  useEffect(() => void load(), [load]);

  if (user && user.role !== "admin") return <Navigate to="/" replace />;

  const patch = async (id: number, body: object) => {
    setError("");
    try {
      await api(`/api/admin/users/${id}`, { method: "PATCH", body });
      await load();
    } catch (e) { setError(e instanceof Error ? e.message : String(e)); }
  };

  const create = async (e: FormEvent) => {
    e.preventDefault();
    setError("");
    try {
      await api("/api/admin/users", { method: "POST", body: form });
      setForm({ username: "", password: "", role: "user" });
      await load();
    } catch (err) { setError(err instanceof Error ? err.message : String(err)); }
  };

  return (
    <div>
      <h1>Verwaltung</h1>
      {error && <p className="error">{error}</p>}
      <section className="card">
        <h2>Benutzer</h2>
        <div className="table-wrap">
          <table className="data">
            <thead><tr><th>Name</th><th>Quelle</th><th>Rolle</th><th>Status</th><th>Letzter Login</th><th /></tr></thead>
            <tbody>
              {users.map((u) => (
                <tr key={u.id} className={u.is_active ? "" : "st-ignored"}>
                  <td>{u.username}</td><td>{u.provider}</td><td>{u.role}</td><td>{u.is_active ? "aktiv" : "gesperrt"}</td>
                  <td>{u.last_login_at ? new Date(u.last_login_at).toLocaleString("de-DE") : "–"}</td>
                  <td className="actions">
                    <button onClick={() => void patch(u.id, { role: u.role === "admin" ? "user" : "admin" })}>{u.role === "admin" ? "Zu Benutzer" : "Zu Admin"}</button>
                    <button onClick={() => void patch(u.id, { is_active: !u.is_active })}>{u.is_active ? "Sperren" : "Entsperren"}</button>
                    {u.provider === "local" && <button onClick={() => { const pw = prompt("Neues Passwort (min. 10 Zeichen)"); if (pw) void patch(u.id, { password: pw }); }}>Passwort</button>}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <form onSubmit={create} className="inline-form">
          <input placeholder="Benutzername" value={form.username} onChange={(e) => setForm({ ...form, username: e.target.value })} required />
          <input type="password" placeholder="Passwort (min. 10 Zeichen)" minLength={10} value={form.password} onChange={(e) => setForm({ ...form, password: e.target.value })} required />
          <select value={form.role} onChange={(e) => setForm({ ...form, role: e.target.value })}><option value="user">Benutzer</option><option value="admin">Admin</option></select>
          <button className="primary">Lokalen Benutzer anlegen</button>
        </form>
      </section>

      <BackupsPanel />

      <section className="card">
        <h2>Protokoll (letzte 100)</h2>
        <div className="table-wrap tall">
          <table className="data">
            <thead><tr><th>Zeit</th><th>Benutzer</th><th>Aktion</th><th>Ziel</th><th>IP</th><th>Details</th></tr></thead>
            <tbody>
              {audit.map((a) => (
                <tr key={a.id}>
                  <td>{new Date(a.ts).toLocaleString("de-DE")}</td><td>{a.username}</td><td>{a.action}</td><td>{a.target}</td><td>{a.ip}</td>
                  <td className="muted">{Object.keys(a.detail).length ? JSON.stringify(a.detail) : ""}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>
    </div>
  );
}
