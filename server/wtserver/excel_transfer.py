"""Excel-Werkzeuge ohne Projektbezug: zwei hochgeladene .xlsx-Dateien miteinander abgleichen.

1. `transfer`: Werte aus Quelldatei in Zieldatei übertragen, Zeilen werden über eine Schlüsselspalte (z. B. Kabelnummer)
   zugeordnet. Vorhandene Werte der gewählten Spalten werden geändert, fehlende Zielspalten ergänzt.
2. `fill_by_key`: Schlüssel und Wert stehen in Spalten der Quelldatei. Der Schlüssel wird in der Zieldatei auf allen
   Blättern gesucht; dort wird der Wert in der Zielspalte derselben Zeile eingetragen.

Die Zieldatei wird mit openpyxl geladen und gespeichert: Zellformate und Farben bleiben erhalten, Diagramme, Bilder
und Makros nicht.
"""
from __future__ import annotations

import re
from io import BytesIO
from typing import Any

from openpyxl import load_workbook
from openpyxl.cell.cell import MergedCell
from openpyxl.utils import column_index_from_string, get_column_letter

MAX_LIST = 200  # so viele Einzelfälle werden höchstens aufgelistet


class ExcelToolError(ValueError):
    pass


def norm(value: Any) -> str:
    """Schlüssel vergleichbar machen: Leerraum und Groß-/Kleinschreibung egal, 12.0 == 12."""
    if value is None or isinstance(value, bool):
        return ""
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return " ".join(str(value).split()).casefold()


def _shown(value: Any) -> str:
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return " ".join(str(value).split())


def _empty(value: Any) -> bool:
    return value is None or (isinstance(value, str) and not value.strip())


def _open(data: bytes, *, values: bool, read_only: bool):
    try:
        return load_workbook(BytesIO(data), read_only=read_only, data_only=values)
    except Exception as exc:  # noqa: BLE001 - zip/xml/Format-Fehler alle gleich behandeln
        raise ExcelToolError("Keine gültige .xlsx-Datei (ältere .xls-Dateien bitte in Excel als .xlsx speichern).") from exc


def _sheet(wb: Any, name: str):
    if not name:
        return wb.worksheets[0]
    if name not in wb.sheetnames:
        raise ExcelToolError(f"Blatt „{name}“ gibt es nicht in der Datei.")
    return wb[name]


def _headers(ws: Any, row: int) -> dict[str, int]:
    """Spaltenname -> Spaltennummer (1-basiert) aus der Kopfzeile; bei doppelten Namen gilt der erste."""
    if row < 1:
        raise ExcelToolError("Die Kopfzeile muss mindestens 1 sein.")
    out: dict[str, int] = {}
    for cells in ws.iter_rows(min_row=row, max_row=row, values_only=True):
        for i, value in enumerate(cells, 1):
            name = "" if value is None else str(value).strip()
            if name and name not in out:
                out[name] = i
        break
    return out


def inspect(data: bytes, header_row: int = 1) -> list[dict[str, Any]]:
    wb = _open(data, values=True, read_only=True)
    try:
        sheets = []
        for ws in wb.worksheets:
            if hasattr(ws, "reset_dimensions"):
                ws.reset_dimensions()
            sheets.append({"name": ws.title,
                           "columns": [{"name": n, "letter": get_column_letter(i)} for n, i in _headers(ws, header_row).items()]})
        return sheets
    finally:
        wb.close()


def _need(headers: dict[str, int], name: str, what: str) -> int:
    if name not in headers:
        raise ExcelToolError(f"{what}: Spalte „{name}“ nicht gefunden (Kopfzeile prüfen).")
    return headers[name]


def _lookup(data: bytes, sheet: str, header_row: int, key: str, value_columns: list[str]):
    """Quelldatei lesen: normalisierter Schlüssel -> Werte der gewählten Spalten (erste Zeile gewinnt)."""
    wb = _open(data, values=True, read_only=True)
    try:
        ws = _sheet(wb, sheet)
        if hasattr(ws, "reset_dimensions"):
            ws.reset_dimensions()
        headers = _headers(ws, header_row)
        key_i = _need(headers, key, "Quelldatei")
        value_i = [_need(headers, c, "Quelldatei") for c in value_columns]
        table: dict[str, list[Any]] = {}
        shown: dict[str, str] = {}
        duplicates: dict[str, int] = {}
        for cells in ws.iter_rows(min_row=header_row + 1, values_only=True):
            k = norm(cells[key_i - 1] if key_i <= len(cells) else None)
            if not k:
                continue
            if k in table:
                duplicates[k] = duplicates.get(k, 1) + 1
                continue
            table[k] = [cells[i - 1] if i <= len(cells) else None for i in value_i]
            shown[k] = _shown(cells[key_i - 1])
        return table, shown, duplicates
    finally:
        wb.close()


def _save(wb: Any) -> bytes:
    out = BytesIO()
    wb.save(out)
    return out.getvalue()


# ---- Werkzeug 1: Spalten über Schlüssel übertragen ----

def transfer(source: bytes, target: bytes, cfg: dict[str, Any], apply: bool) -> tuple[dict[str, Any], bytes | None]:
    pairs: list[dict[str, str]] = cfg["pairs"]
    if not pairs:
        raise ExcelToolError("Keine Spalte zum Übertragen gewählt.")
    table, shown, duplicates = _lookup(source, cfg["source_sheet"], cfg["source_header"], cfg["source_key"],
                                       [p["source"] for p in pairs])
    wb = _open(target, values=False, read_only=False)
    ws = _sheet(wb, cfg["target_sheet"])
    header = cfg["target_header"]
    headers = _headers(ws, header)
    key_col = _need(headers, cfg["target_key"], "Zieldatei")
    next_col = max([ws.max_column, *headers.values()]) + 1
    columns: list[int] = []
    new_columns: list[str] = []
    for pair in pairs:
        name = pair["target"].strip() or pair["source"]
        if name not in headers:
            headers[name] = next_col
            new_columns.append(name)
            if apply:
                ws.cell(header, next_col).value = name
            next_col += 1
        columns.append(headers[name])
    names = [p["target"].strip() or p["source"] for p in pairs]

    counts = {"rows_matched": 0, "rows_changed": 0, "cells_changed": 0, "cells_unchanged": 0, "cells_kept": 0,
              "cells_merged_skipped": 0}
    changes: list[dict[str, Any]] = []
    missing: list[str] = []
    missing_total = 0
    seen: set[str] = set()
    for r in range(header + 1, ws.max_row + 1):
        raw = ws.cell(r, key_col).value
        k = norm(raw)
        if not k:
            continue
        if k not in table:
            missing_total += 1
            if len(missing) < MAX_LIST:
                missing.append(_shown(raw))
            continue
        seen.add(k)
        counts["rows_matched"] += 1
        row_changed = False
        for name, col, new in zip(names, columns, table[k]):
            if cfg["skip_empty"] and _empty(new):
                continue
            cell = ws.cell(r, col)
            if isinstance(cell, MergedCell):
                counts["cells_merged_skipped"] += 1
                continue
            old = cell.value
            if cfg["overwrite"] == "empty" and not _empty(old):
                counts["cells_kept"] += 1
                continue
            if old == new or (_empty(old) and _empty(new)):
                counts["cells_unchanged"] += 1
                continue
            counts["cells_changed"] += 1
            row_changed = True
            if len(changes) < MAX_LIST:
                changes.append({"row": r, "key": shown[k], "column": name, "old": _plain(old), "new": _plain(new)})
            if apply:
                cell.value = new
        counts["rows_changed"] += row_changed
    only_source = [shown[k] for k in table if k not in seen]
    summary = {**counts, "new_columns": new_columns, "changes": changes, "missing_in_source": missing,
               "missing_in_source_total": missing_total, "only_in_source": only_source[:MAX_LIST],
               "only_in_source_total": len(only_source),
               "duplicate_keys": [shown[k] for k in list(duplicates)[:MAX_LIST]], "duplicate_total": len(duplicates)}
    return summary, (_save(wb) if apply else None)


# ---- Werkzeug 2: Wert zum Schlüssel überall in der Zieldatei eintragen ----

def _column_in(headers: dict[str, int], spec: str) -> int | None:
    """Spalte aus Kopfzeilen-Name, sonst aus Spaltenbuchstabe (A, B, AA ...)."""
    spec = spec.strip()
    for name, index in headers.items():
        if name.casefold() == spec.casefold():
            return index
    if re.fullmatch(r"[A-Za-z]{1,3}", spec):
        index = column_index_from_string(spec.upper())
        return index if index <= 16384 else None
    return None


def fill_by_key(source: bytes, target: bytes, cfg: dict[str, Any], apply: bool) -> tuple[dict[str, Any], bytes | None]:
    table, shown, duplicates = _lookup(source, cfg["source_sheet"], cfg["source_header"], cfg["source_key"],
                                       [cfg["source_value"]])
    values: dict[str, Any] = {}
    empty_value: list[str] = []
    for k, (value,) in table.items():
        if cfg["skip_empty"] and _empty(value):
            empty_value.append(shown[k])
            continue
        values[k] = value
    wb = _open(target, values=False, read_only=False)
    header = cfg["target_header"]
    wanted = {s.casefold() for s in cfg["target_sheets"]}
    found: dict[str, int] = {}
    changes: list[dict[str, Any]] = []
    sheets: list[dict[str, Any]] = []
    skipped: list[str] = []
    row_clash = 0
    counts = {"cells_changed": 0, "cells_unchanged": 0, "cells_kept": 0, "cells_merged_skipped": 0}
    for ws in wb.worksheets:
        if wanted and ws.title.casefold() not in wanted:
            continue
        headers = _headers(ws, header)
        out_col = _column_in(headers, cfg["target_column"])
        key_col = _column_in(headers, cfg["target_key_column"]) if cfg["target_key_column"].strip() else None
        if out_col is None or (cfg["target_key_column"].strip() and key_col is None):
            skipped.append(ws.title)
            continue
        hits: dict[int, tuple[str, int]] = {}  # Zeile -> (Schlüssel, Zelle des Fundes)
        count = changed = 0
        columns = [key_col] if key_col else None
        for row in ws.iter_rows(min_row=header + 1):
            for cell in row:
                if isinstance(cell, MergedCell) or cell.value is None or cell.column == out_col:
                    continue
                if columns and cell.column not in columns:
                    continue
                k = norm(cell.value)
                if k not in values:
                    continue
                found[k] = found.get(k, 0) + 1
                if cell.row in hits and hits[cell.row][0] != k:
                    row_clash += 1  # zwei verschiedene Schlüssel in einer Zeile: der erste gilt
                    continue
                hits[cell.row] = (k, cell.column)
        for r, (k, _col) in hits.items():
            count += 1
            cell = ws.cell(r, out_col)
            if isinstance(cell, MergedCell):
                counts["cells_merged_skipped"] += 1
                continue
            new, old = values[k], cell.value
            if cfg["overwrite"] == "empty" and not _empty(old):
                counts["cells_kept"] += 1
                continue
            if old == new:
                counts["cells_unchanged"] += 1
                continue
            counts["cells_changed"] += 1
            changed += 1
            if len(changes) < MAX_LIST:
                changes.append({"sheet": ws.title, "row": r, "key": shown[k], "column": get_column_letter(out_col),
                                "old": _plain(old), "new": _plain(new)})
            if apply:
                cell.value = new
        sheets.append({"sheet": ws.title, "found": count, "changed": changed, "column": get_column_letter(out_col)})
    not_found = [shown[k] for k in values if k not in found]
    summary = {**counts, "keys_total": len(values), "keys_found": len(found), "sheets": sheets,
               "sheets_skipped": skipped, "changes": changes, "not_found": not_found[:MAX_LIST],
               "not_found_total": len(not_found), "found_multiple": sum(1 for n in found.values() if n > 1),
               "row_clash": row_clash, "empty_value": empty_value[:MAX_LIST], "empty_value_total": len(empty_value),
               "duplicate_keys": [shown[k] for k in list(duplicates)[:MAX_LIST]], "duplicate_total": len(duplicates)}
    return summary, (_save(wb) if apply else None)


def _plain(value: Any) -> Any:
    """Für die JSON-Antwort: nur Text und Zahlen, alles andere als Text."""
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    return str(value)
