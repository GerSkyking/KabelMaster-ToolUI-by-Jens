import { ReactNode, createContext, useCallback, useContext, useEffect, useMemo, useState } from "react";
import { ApiError, OfflineError, api, onUnauthorized } from "./api";
import { kvGet, kvSet } from "./db";

export interface User {
  id: number;
  username: string;
  display_name: string;
  email: string;
  role: "admin" | "user";
  provider: string;
}

export interface AuthConfig {
  local: boolean;
  ldap: boolean;
  oidc: string | null;
  oauth2: string | null;
}

interface AuthValue {
  status: "loading" | "in" | "out";
  user: User | null;
  config: AuthConfig | null;
  offline: boolean; // angemeldet aus dem lokalen Speicher, Server aktuell nicht erreichbar
  expired: boolean; // Server hat die Sitzung abgelehnt; lokal kann weitergearbeitet werden
  login: (username: string, password: string) => Promise<void>;
  logout: () => Promise<void>;
}

const Ctx = createContext<AuthValue | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [status, setStatus] = useState<AuthValue["status"]>("loading");
  const [user, setUser] = useState<User | null>(null);
  const [config, setConfig] = useState<AuthConfig | null>(null);
  const [offline, setOffline] = useState(false);
  const [expired, setExpired] = useState(false);

  useEffect(() => {
    let alive = true;
    (async () => {
      try {
        const cfg = await api<AuthConfig>("/api/auth/config", { quiet401: true });
        if (alive) setConfig(cfg);
        void kvSet("authConfig", cfg);
      } catch {
        const cached = await kvGet<AuthConfig>("authConfig");
        if (alive && cached) setConfig(cached);
      }
      try {
        const me = await api<User>("/api/auth/me", { quiet401: true });
        void kvSet("user", me);
        if (alive) {
          setUser(me);
          setStatus("in");
        }
      } catch (e) {
        if (e instanceof OfflineError) {
          const cached = await kvGet<User>("user");
          if (alive) {
            setUser(cached ?? null);
            setOffline(!!cached);
            setStatus(cached ? "in" : "out");
          }
        } else if (alive) setStatus("out");
      }
    })();
    const off = onUnauthorized(() => setExpired(true));
    return () => {
      alive = false;
      off();
    };
  }, []);

  const login = useCallback(async (username: string, password: string) => {
    try {
      const me = await api<User>("/api/auth/login", { method: "POST", body: { username, password }, quiet401: true });
      void kvSet("user", me);
      setUser(me);
      setOffline(false);
      setExpired(false);
      setStatus("in");
    } catch (e) {
      if (e instanceof ApiError || e instanceof OfflineError) throw e;
      throw new Error("Anmeldung fehlgeschlagen");
    }
  }, []);

  const logout = useCallback(async () => {
    try {
      await api("/api/auth/logout", { method: "POST", quiet401: true });
    } catch {
      /* offline: Cookie läuft von selbst ab */
    }
    setUser(null);
    setStatus("out");
  }, []);

  const value = useMemo(
    () => ({ status, user, config, offline, expired, login, logout }),
    [status, user, config, offline, expired, login, logout],
  );
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

export function useAuth(): AuthValue {
  const value = useContext(Ctx);
  if (!value) throw new Error("AuthProvider fehlt");
  return value;
}
