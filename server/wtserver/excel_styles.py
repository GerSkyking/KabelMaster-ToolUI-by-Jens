"""Zellfarben aus Excel-Dateien (Füllung und Schriftfarbe) für die Anzeige im Web.

Je Zeile wird ``{"Spalte": [Hintergrund, Schrift]}`` geliefert (Hex ``#rrggbb`` oder ``""``), nur für Zellen mit Farbe.
Ausgerichtet an den Datenzeilen, die pandas aus demselben Blatt liest (Zeile 1 = Kopfzeile).
Nur .xlsx; bei .xls/.csv gibt es keine Farben.
"""
from __future__ import annotations

import colorsys
import re
from pathlib import Path
from typing import Any

STYLE_KEY = "__style"  # Schlüssel in den Zeilendaten; beginnt mit "__", ist keine Spalte
_THEME_ORDER = ["lt1", "dk1", "lt2", "dk2", "accent1", "accent2", "accent3", "accent4", "accent5", "accent6", "hlink", "folHlink"]
_DEFAULT_THEME = ["FFFFFF", "000000", "EEECE1", "1F497D", "4F81BD", "C0504D", "9BBB59", "8064A2", "4BACC6", "F79646", "0000FF", "800080"]


def _theme_colors(workbook: Any) -> list[str]:
    xml = getattr(workbook, "loaded_theme", None)
    if not xml:
        return _DEFAULT_THEME
    text = xml.decode("utf-8", "ignore") if isinstance(xml, bytes) else str(xml)
    colors: list[str] = []
    for name in _THEME_ORDER:
        match = re.search(rf"<a:{name}>\s*<a:(?:srgbClr val|sysClr[^>]*lastClr)=\"([0-9A-Fa-f]{{6}})\"", text)
        colors.append(match.group(1).upper() if match else _DEFAULT_THEME[len(colors)])
    return colors


def _tint(hex6: str, tint: float) -> str:
    if not tint:
        return hex6
    r, g, b = (int(hex6[i:i + 2], 16) / 255 for i in (0, 2, 4))
    h, lum, s = colorsys.rgb_to_hls(r, g, b)
    lum = lum * (1 + tint) if tint < 0 else lum * (1 - tint) + tint
    r, g, b = colorsys.hls_to_rgb(h, max(0.0, min(1.0, lum)), s)
    return "".join(f"{round(v * 255):02X}" for v in (r, g, b))


def _resolve(color: Any, theme: list[str]) -> str:
    """Excel-Farbobjekt -> '#rrggbb' oder '' (keine/automatische Farbe)."""
    if color is None:
        return ""
    try:
        kind = color.type
        if kind == "rgb":
            value = str(color.rgb or "")
            if len(value) == 8:
                value = value[2:]  # ARGB -> RGB
            return f"#{value.lower()}" if re.fullmatch(r"[0-9A-Fa-f]{6}", value) else ""
        if kind == "theme":
            index = int(color.theme)
            if 0 <= index < len(theme):
                return "#" + _tint(theme[index], float(color.tint or 0)).lower()
        if kind == "indexed":
            from openpyxl.styles.colors import COLOR_INDEX
            index = int(color.indexed)
            if 0 <= index < len(COLOR_INDEX):
                value = COLOR_INDEX[index][2:]
                return f"#{value.lower()}" if re.fullmatch(r"[0-9A-Fa-f]{6}", value) and index not in (64, 65) else ""
    except (AttributeError, TypeError, ValueError):
        return ""
    return ""


def read_styles(path: Path, sheet: str | None = None, row_count: int | None = None) -> list[dict[str, list[str]]]:
    """Farben je Datenzeile des Blatts (erstes Blatt, wenn ``sheet`` fehlt). Bei Fehlern/ohne Farben: leere Liste."""
    if path.suffix.lower() != ".xlsx":
        return []
    try:
        from openpyxl import load_workbook
        workbook = load_workbook(path, read_only=False, data_only=True)
    except Exception:  # noqa: BLE001 - Farben sind nur Zusatz, der Import darf daran nie scheitern
        return []
    try:
        theme = _theme_colors(workbook)
        worksheet = workbook[sheet] if sheet and sheet in workbook.sheetnames else workbook.worksheets[0]
        rows = worksheet.iter_rows(min_row=1)
        header_row = next(rows, None)
        if header_row is None:
            return []
        names = _column_names([c.value for c in header_row])
        out: list[dict[str, list[str]]] = []
        for cells in rows:
            if row_count is not None and len(out) >= row_count:
                break
            styles: dict[str, list[str]] = {}
            for name, cell in zip(names, cells):
                background = foreground = ""
                fill = getattr(cell, "fill", None)
                if fill is not None and fill.fill_type == "solid":
                    background = _resolve(fill.fgColor, theme)
                    if background == "#ffffff":
                        background = ""
                font = getattr(cell, "font", None)
                if font is not None and font.color is not None:
                    foreground = _resolve(font.color, theme)
                    if foreground == "#000000":
                        foreground = ""
                if background or foreground:
                    styles[name] = [background, foreground]
            out.append(styles)
        return out if any(out) else []
    except Exception:  # noqa: BLE001
        return []
    finally:
        workbook.close()


def _column_names(raw: list[Any]) -> list[str]:
    """Gleiche Normalisierung wie beim Import, damit die Namen zu den Spalten der Liste passen."""
    from core.io.excel_reader import _normalize_columns
    seen: dict[str, int] = {}
    renamed: list[Any] = []
    for value in raw:  # pandas nennt doppelte Spalten "A", "A.1", "A.2" ...
        key = "" if value is None else str(value).strip()
        if key and key in seen:
            seen[key] += 1
            renamed.append(f"{key}.{seen[key]}")
        else:
            if key:
                seen[key] = 0
            renamed.append(value)
    return _normalize_columns(renamed)


def attach(rows: list[dict[str, Any]], styles: list[dict[str, list[str]]], offset: int = 0) -> None:
    """Hängt die Farben an die Zeilendaten (``offset``: erste Zeile in ``styles``)."""
    for i, row in enumerate(rows):
        if offset + i < len(styles) and styles[offset + i]:
            row[STYLE_KEY] = styles[offset + i]
