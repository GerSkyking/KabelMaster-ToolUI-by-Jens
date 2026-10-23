import { Component, ErrorInfo, ReactNode } from "react";

interface State { error: Error | null }

/** Fängt Darstellungsfehler ab, damit nicht die ganze Seite weiß bleibt. Lokale Daten (IndexedDB) bleiben erhalten. */
export class ErrorBoundary extends Component<{ children: ReactNode }, State> {
  state: State = { error: null };

  static getDerivedStateFromError(error: Error): State {
    return { error };
  }

  componentDidCatch(error: Error, info: ErrorInfo): void {
    console.error("UI-Fehler", error, info.componentStack);
  }

  render() {
    if (!this.state.error) return this.props.children;
    return (
      <div className="card pad">
        <h2>Hier ist etwas schiefgegangen</h2>
        <p className="muted">Deine lokalen, noch nicht übertragenen Änderungen sind nicht verloren.</p>
        <p><code>{this.state.error.message}</code></p>
        <button className="primary" onClick={() => window.location.reload()}>Seite neu laden</button>{" "}
        <a className="button" href="/">Zu den Projekten</a>
      </div>
    );
  }
}
