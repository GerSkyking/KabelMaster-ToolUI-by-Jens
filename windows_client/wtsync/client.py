"""Sync-Client für die Windows-App und Skripte: arbeitet mit API-Key, lokal in Excel, überträgt später.

Ablauf (halb offline):
  1. pull():  Liste vom Server holen -> lokale Excel-Datei + Snapshot (``<datei>.wtsync.json``)
  2. Excel lokal bearbeiten (auch ohne Verbindung)
  3. push():  geänderte Zellen mit dem Snapshot vergleichen, feldweise übertragen, Konflikte melden,
              Datei und Snapshot mit dem Server-Stand aktualisieren

Zeilen werden über ihre Position zugeordnet (Reihenfolge wie beim Pull). Zusätzliche Zeilen am Ende werden
neu angelegt; fehlende Zeilen werden nicht gelöscht, sondern gemeldet.
"""
from __future__ import annotations

import json
import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx
import pandas as pd

SNAPSHOT_SUFFIX = ".wtsync.json"


class SyncError(Exception):
    pass


@dataclass
class PushReport:
    changed_rows: int = 0
    created_rows: int = 0
    new_columns: list[str] = field(default_factory=list)
    conflicts: list[dict[str, Any]] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    missing_rows: int = 0


def _clean(value: Any) -> Any:
    """Excel-/pandas-Werte in JSON-Werte wandeln; leere Zellen werden zu None."""
    if value is None:
        return None
    if hasattr(value, "item"):
        value = value.item()
    if isinstance(value, float):
        if math.isnan(value) or math.isinf(value):
            return None
        return int(value) if value.is_integer() else value
    if isinstance(value, str):
        return value if value.strip() else None
    if hasattr(value, "strftime"):
        return value.strftime("%d.%m.%Y")
    return value


def snapshot_path(excel_path: Path) -> Path:
    return excel_path.with_name(excel_path.name + SNAPSHOT_SUFFIX)


class WtClient:
    def __init__(self, base_url: str = "", api_key: str = "", http: httpx.Client | None = None) -> None:
        if http is None:
            http = httpx.Client(base_url=base_url.rstrip("/"), headers={"X-API-Key": api_key}, timeout=30)
        self.http = http

    # ---- Server ----

    def _call(self, method: str, path: str, **kwargs: Any) -> Any:
        try:
            response = self.http.request(method, path, **kwargs)
        except httpx.TransportError as exc:
            raise SyncError(f"Server nicht erreichbar: {exc}") from exc
        if response.status_code >= 400:
            try:
                detail = response.json().get("detail", response.text)
            except ValueError:
                detail = response.text
            raise SyncError(f"{response.status_code}: {detail}")
        return response.json() if response.content else None

    def projects(self) -> list[dict[str, Any]]:
        return self._call("GET", "/api/projects")

    def dataset(self, dataset_id: int) -> dict[str, Any]:
        return self._call("GET", f"/api/datasets/{dataset_id}")

    # ---- Pull ----

    def pull(self, dataset_id: int, excel_path: Path) -> pd.DataFrame:
        """Lädt den Datensatz als Excel-Datei und legt den Snapshot daneben ab."""
        meta = self.dataset(dataset_id)
        data = self._call("GET", f"/api/datasets/{dataset_id}/rows", params={"since": 0})
        columns: list[str] = data["columns"]
        rows = data["rows"]
        frame = pd.DataFrame([{c: r["data"].get(c) for c in columns} for r in rows], columns=columns)
        frame.astype(object).where(frame.notna(), None).to_excel(excel_path, index=False)
        snapshot = {
            "dataset_id": dataset_id, "name": meta["name"], "seq": data["seq"], "columns": columns,
            "rows": [{"id": r["id"], "rev": r["rev"], "data": {c: r["data"].get(c) for c in columns}} for r in rows],
        }
        snapshot_path(excel_path).write_text(json.dumps(snapshot, ensure_ascii=False), encoding="utf-8")
        return frame

    # ---- Push ----

    def push(self, excel_path: Path, snapshot: Path | None = None) -> PushReport:
        """Überträgt Änderungen. ``snapshot`` nur angeben, wenn die Datei unter anderem Namen gespeichert wurde."""
        snap_file = snapshot_path(excel_path)
        if snapshot is not None and snapshot != snap_file:
            snap_file.write_bytes(snapshot.read_bytes())
        if not snap_file.is_file():
            raise SyncError(f"Kein Snapshot gefunden ({snap_file.name}) - die Datei wurde nicht mit 'pull' erzeugt.")
        snap = json.loads(snap_file.read_text(encoding="utf-8"))
        frame = pd.read_excel(excel_path, dtype=object)
        dataset_id = snap["dataset_id"]
        report = PushReport()

        columns: list[str] = snap["columns"]
        new_columns = [str(c) for c in frame.columns if str(c) not in columns]
        if new_columns:
            self._call("PATCH", f"/api/datasets/{dataset_id}", json={"add_columns": new_columns})
            report.new_columns = new_columns
            columns = columns + new_columns

        known = snap["rows"]
        ops: list[dict[str, Any]] = []
        for position, record in enumerate(frame.to_dict("records")):
            current = {str(k): _clean(v) for k, v in record.items() if str(k) in columns}
            if position >= len(known):
                if any(v is not None for v in current.values()):
                    ops.append({"client_id": str(position), "patch": {k: v for k, v in current.items() if v is not None}})
                continue
            base = known[position]
            patch = {c: current.get(c) for c in columns if current.get(c) != base["data"].get(c)}
            if patch:
                ops.append({"id": base["id"], "base_rev": base["rev"], "patch": patch,
                            "base": {c: base["data"].get(c) for c in patch}})
        report.missing_rows = max(len(known) - len(frame), 0)

        if ops:
            result = self._call("POST", f"/api/datasets/{dataset_id}/sync", json={"ops": ops})
            for op, res in zip(ops, result["results"]):
                if res["status"] == "error":
                    report.errors.append(res.get("error", "Unbekannter Fehler"))
                    continue
                report.created_rows += 1 if op.get("id") is None else 0
                report.changed_rows += 0 if op.get("id") is None else 1
                for field_name in res["conflicts"]:
                    report.conflicts.append({"row": op["id"], "field": field_name, "mine": op["patch"].get(field_name),
                                             "theirs": res["row"]["data"].get(field_name)})
        self.pull(dataset_id, excel_path)  # Datei und Snapshot auf den Server-Stand bringen
        return report
