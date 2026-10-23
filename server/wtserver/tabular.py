"""Excel <-> Datensatz: Import über das gemeinsame core/-Modul, Export zurück nach .xlsx."""
from __future__ import annotations

import math
from datetime import date, datetime
from io import BytesIO
from pathlib import Path
from typing import Any

import pandas as pd

from core.io.excel_reader import (
    EmptyFileError, ExcelReader, ExcelReadError, _engine_for, _normalize_columns,
)

SHEET_COLUMN = "Blatt"  # Spalte mit dem Blattnamen, wenn alle Blätter einer Mappe zu einer Liste zusammengefasst werden


def json_value(value: Any) -> Any:
    """Macht Zellwerte (numpy, Timestamp, NaN) JSON-tauglich."""
    if value is None:
        return None
    if isinstance(value, (datetime, pd.Timestamp)):
        return None if pd.isna(value) else value.strftime("%d.%m.%Y")
    if isinstance(value, date):
        return value.strftime("%d.%m.%Y")
    if hasattr(value, "item"):  # numpy-Skalare
        value = value.item()
    if isinstance(value, float):
        if math.isnan(value) or math.isinf(value):
            return None
        return int(value) if value.is_integer() and abs(value) < 1e15 else value
    if isinstance(value, (int, bool, str)):
        return value
    return str(value)


def _rows_of(frame: pd.DataFrame) -> tuple[list[str], list[dict[str, Any]]]:
    columns = list(frame.columns)
    rows = [
        {column: json_value(value) for column, value in zip(columns, record)}
        for record in frame.itertuples(index=False, name=None)
    ]
    return columns, rows


def _read_csv(path: Path) -> pd.DataFrame:
    error: Exception | None = None
    for encoding in ("utf-8-sig", "cp1252"):
        try:
            frame = pd.read_csv(path, sep=None, engine="python", dtype=object, encoding=encoding)
            break
        except UnicodeDecodeError as exc:
            error = exc
        except Exception as exc:  # noqa: BLE001 - Parser-Fehler aller Art als Importfehler melden
            raise ExcelReadError(path, exc) from exc
    else:
        raise ExcelReadError(path, error or ValueError("Zeichensatz nicht erkannt"))
    if frame.shape[1] == 0:
        raise EmptyFileError(path)
    frame.columns = _normalize_columns(list(frame.columns))
    return frame


def sheet_names(path: Path) -> list[str]:
    """Blattnamen einer Excel-Datei (CSV hat genau eine Tabelle)."""
    if path.suffix.lower() == ".csv":
        return ["Tabelle"]
    try:
        with pd.ExcelFile(path, engine=_engine_for(path)) as workbook:
            return [str(name) for name in workbook.sheet_names]
    except Exception as exc:  # noqa: BLE001
        raise ExcelReadError(path, exc) from exc


def read_rows(path: Path, sheet: str | None = None) -> tuple[list[str], list[dict[str, Any]]]:
    """Liest eine Tabelle: das erste Blatt oder das genannte; (Spaltennamen, Zeilen als dict)."""
    if path.suffix.lower() == ".csv":
        return _rows_of(_read_csv(path))
    if not sheet:
        document = ExcelReader().load(path)
        return _rows_of(document.dataframe)
    try:
        frame = pd.read_excel(path, sheet_name=sheet, header=0, engine=_engine_for(path), dtype=object)
    except Exception as exc:  # noqa: BLE001
        raise ExcelReadError(path, exc) from exc
    if frame.shape[1] == 0:
        raise EmptyFileError(path)
    frame.columns = _normalize_columns(list(frame.columns))
    return _rows_of(frame)


def read_workbook(path: Path) -> tuple[list[str], list[dict[str, Any]], list[dict[str, Any]], str]:
    """Alle Blätter zu einer Liste: (Spalten, Zeilen, Blätter mit ihren Spalten, Name der Blatt-Spalte).
    Jede Zeile bekommt den Blattnamen; die Spalten sind die Vereinigung aller Blätter."""
    loaded: list[tuple[str, list[str], list[dict[str, Any]]]] = []
    for name in sheet_names(path):
        try:
            columns, rows = read_rows(path, name)
        except EmptyFileError:
            continue  # leeres Blatt
        loaded.append((name, columns, rows))
    if not loaded:
        raise EmptyFileError(path)
    used = {c for _, columns, _ in loaded for c in columns}
    sheet_column = SHEET_COLUMN
    while sheet_column in used:
        sheet_column += " (Reiter)"
    union: list[str] = []
    for _, columns, _ in loaded:
        union.extend(c for c in columns if c not in union)
    rows_out = [{sheet_column: name, **row} for name, _, rows in loaded for row in rows]
    sheets = [{"name": name, "columns": columns} for name, columns, _ in loaded]
    return [sheet_column, *union], rows_out, sheets, sheet_column


def build_dataframe(columns: list[str], rows: list[dict[str, Any]]) -> pd.DataFrame:
    frame = pd.DataFrame([{c: row.get(c) for c in columns} for row in rows], columns=columns, dtype=object)
    return frame.where(frame.notna(), None)


def _sheet_title(name: str, taken: set[str]) -> str:
    base = "".join(ch for ch in name if ch not in "[]:*?/\\").strip()[:31] or "Blatt"
    title, counter = base, 1
    while title.lower() in taken:
        counter += 1
        suffix = f" ({counter})"
        title = base[: 31 - len(suffix)] + suffix
    taken.add(title.lower())
    return title


def to_workbook_bytes(columns: list[str], rows: list[dict[str, Any]], name: str, settings: dict[str, Any]) -> bytes:
    """Excel-Datei zur Liste. Wurden beim Import alle Blätter zusammengefasst, entsteht wieder eine Mappe mit denselben
    Blättern: je Blatt dessen ursprüngliche Spalten plus neue Spalten, die dort Werte haben (z. B. vom Übersetzer)."""
    sheets = settings.get("sheets")
    if not sheets:
        return to_xlsx_bytes(columns, rows, name)
    sheet_column = settings.get("sheet_column", SHEET_COLUMN)
    grouped: dict[str, list[dict[str, Any]]] = {s["name"]: [] for s in sheets}
    first = sheets[0]["name"]
    for row in rows:
        grouped.get(row.get(sheet_column), grouped[first]).append(row)
    buffer = BytesIO()
    taken: set[str] = set()
    with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
        for sheet in sheets:
            own = [c for c in sheet["columns"] if c in columns]
            extra = [
                c for c in columns
                if c != sheet_column and c not in own
                and any(row.get(c) is not None and str(row.get(c)).strip() != "" for row in grouped[sheet["name"]])
            ]
            build_dataframe(own + extra, grouped[sheet["name"]]).to_excel(
                writer, index=False, sheet_name=_sheet_title(sheet["name"], taken))
    return buffer.getvalue()


def to_xlsx_bytes(columns: list[str], rows: list[dict[str, Any]], sheet: str = "Liste") -> bytes:
    buffer = BytesIO()
    build_dataframe(columns, rows).to_excel(buffer, index=False, sheet_name=sheet[:31], engine="openpyxl")
    return buffer.getvalue()
