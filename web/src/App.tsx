import { ReactNode } from "react";
import { Link, Navigate, Route, Routes, useLocation } from "react-router-dom";
import { useAuth } from "./auth";
import { AccountPage } from "./pages/AccountPage";
import { AdminPage } from "./pages/AdminPage";
import { DatasetPage } from "./pages/DatasetPage";
import { LoginPage } from "./pages/LoginPage";
import { ProjectPage } from "./pages/ProjectPage";
import { ProjectsPage } from "./pages/ProjectsPage";
import { SharePage } from "./pages/SharePage";
import { TemplatesPage } from "./pages/TemplatesPage";

function RequireAuth({ children }: { children: ReactNode }) {
  const { status } = useAuth();
  const location = useLocation();
  if (status === "loading") return <p className="muted pad">Lade …</p>;
  if (status === "out") return <Navigate to="/login" state={{ from: location.pathname }} replace />;
  return <>{children}</>;
}

function Shell({ children }: { children: ReactNode }) {
  const { user, offline, expired, logout } = useAuth();
  return (
    <>
      <header className="top">
        <Link to="/" className="brand">UW Kabel-Master ToolUI <small>by Jens</small></Link>
        <nav>
          <Link to="/">Projekte</Link>
          <Link to="/templates">Vorlagen</Link>
          <Link to="/account">Konto</Link>
          {user?.role === "admin" && <Link to="/admin">Verwaltung</Link>}
        </nav>
        <span className="spacer" />
        <span className="muted who">{user?.display_name}</span>
        <button onClick={() => void logout()}>Abmelden</button>
      </header>
      {offline && <div className="banner warn">Offline-Modus: Der Server ist nicht erreichbar. Gespeicherte Daten sind weiter nutzbar.</div>}
      {expired && !offline && <div className="banner warn">Die Sitzung ist abgelaufen. <Link to="/login">Neu anmelden</Link> - lokale Änderungen gehen nicht verloren.</div>}
      <main>{children}</main>
    </>
  );
}

export function App() {
  return (
    <Routes>
      <Route path="/login" element={<LoginPage />} />
      <Route path="/s/:token" element={<SharePage />} />
      <Route path="/" element={<RequireAuth><Shell><ProjectsPage /></Shell></RequireAuth>} />
      <Route path="/projects/:id" element={<RequireAuth><Shell><ProjectPage /></Shell></RequireAuth>} />
      <Route path="/datasets/:id" element={<RequireAuth><Shell><DatasetPage /></Shell></RequireAuth>} />
      <Route path="/templates" element={<RequireAuth><Shell><TemplatesPage /></Shell></RequireAuth>} />
      <Route path="/account" element={<RequireAuth><Shell><AccountPage /></Shell></RequireAuth>} />
      <Route path="/admin" element={<RequireAuth><Shell><AdminPage /></Shell></RequireAuth>} />
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  );
}
