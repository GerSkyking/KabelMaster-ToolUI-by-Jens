"""Excel <-> Datensatz: Import über das gemeinsame core/-Modul, Export zurück nach .xlsx."""
from __future__ import annotations

import math
from datetime import date, datetime
from io import BytesIO
from pathlib import Path
from typing import Any

import pandas as pd

from core.io.excel_reader import ExcelReader


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


def read_rows(path: Path) -> tuple[list[str], list[dict[str, Any]]]:
    """Liest die erste Tabelle einer Excel-Datei: (Spaltennamen, Zeilen als dict)."""
    document = ExcelReader().load(path)
    columns = list(document.columns)
    rows = [
        {column: json_value(value) for column, value in zip(columns, record)}
        for record in document.dataframe.itertuples(index=False, name=None)
    ]
    return columns, rows


def build_dataframe(columns: list[str], rows: list[dict[str, Any]]) -> pd.DataFrame:
    frame = pd.DataFrame([{c: row.get(c) for c in columns} for row in rows], columns=columns, dtype=object)
    return frame.where(frame.notna(), None)


def to_xlsx_bytes(columns: list[str], rows: list[dict[str, Any]], sheet: str = "Liste") -> bytes:
    buffer = BytesIO()
    build_dataframe(columns, rows).to_excel(buffer, index=False, sheet_name=sheet[:31], engine="openpyxl")
    return buffer.getvalue()
