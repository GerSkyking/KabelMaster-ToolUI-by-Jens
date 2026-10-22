import { useMemo } from "react";
import { useParams } from "react-router-dom";
import { CableView } from "../components/CableView";
import { shareBackend } from "../sync";

/** Öffentliche Ansicht über einen temporären Link - ohne Anmeldung. */
export function SharePage() {
  const { token = "" } = useParams();
  const backend = useMemo(() => shareBackend(token), [token]);
  return (
    <>
      <header className="top"><span className="brand">UW Kabel-Master ToolUI by Jens</span><span className="spacer" /><span className="muted">Gastzugang</span></header>
      <main><CableView backend={backend} /></main>
    </>
  );
}
