import { FormEvent, useState } from "react";
import { Navigate, useLocation, useSearchParams } from "react-router-dom";
import { ApiError, OfflineError } from "../api";
import { useAuth } from "../auth";

export function LoginPage() {
  const { status, config, login } = useAuth();
  const [params] = useSearchParams();
  const location = useLocation();
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState(
    params.get("error") === "extern" ? "Externe Anmeldung fehlgeschlagen." :
    params.get("error") === "gesperrt" ? "Dieses Konto ist gesperrt oder darf sich nicht selbst anlegen." : "",
  );
  const [busy, setBusy] = useState(false);

  if (status === "in") return <Navigate to={(location.state as { from?: string } | null)?.from ?? "/"} replace />;

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setError("");
    try {
      await login(username, password);
    } catch (err) {
      setError(err instanceof OfflineError ? "Server nicht erreichbar." : err instanceof ApiError ? err.message : "Anmeldung fehlgeschlagen.");
    } finally {
      setBusy(false);
    }
  };

  const showForm = config ? config.local || config.ldap : true;
  return (
    <div className="login">
      <h1>UW Kabel-Master ToolUI by Jens</h1>
      {showForm && (
        <form onSubmit={submit} className="card">
          <label>Benutzername<input autoFocus autoComplete="username" value={username} onChange={(e) => setUsername(e.target.value)} required /></label>
          <label>Passwort<input type="password" autoComplete="current-password" value={password} onChange={(e) => setPassword(e.target.value)} required /></label>
          {config?.ldap && <p className="muted">Auch mit LDAP-/Domänen-Konto möglich.</p>}
          {error && <p className="error">{error}</p>}
          <button className="primary" disabled={busy}>{busy ? "Anmelden …" : "Anmelden"}</button>
        </form>
      )}
      {(config?.oidc || config?.oauth2) && (
        <div className="card external">
          {config.oidc && <a className="button" href="/api/auth/oidc/login">Anmelden mit {config.oidc}</a>}
          {config.oauth2 && <a className="button" href="/api/auth/oauth2/login">Anmelden mit {config.oauth2}</a>}
        </div>
      )}
      {!showForm && error && <p className="error">{error}</p>}
    </div>
  );
}
