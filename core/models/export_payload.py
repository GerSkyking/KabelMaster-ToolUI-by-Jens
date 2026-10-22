"""Exporterneutrales Zwischenmodell: einzige Eingabe für XlsxExporter und PdfExporter.

Sortierung, Trennzeilen-Einfügung und Spaltenauswahl/-reihenfolge sind hier
bereits final aufgelöst - die Exporter selbst enthalten dazu keine eigene Logik.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from core.models.export_header_config import ExportHeaderConfig


@dataclass
class ExportColumn:
    name: str
    width_px: int


@dataclass
class ExportRow:
    values: list[str]
    is_separator: bool = False
    # Farbmarkierung (Reiter 3): vorgeblendeter Hex-Wert (#RRGGBB) oder None.
    # row_color färbt die gesamte Zeile; cell_colors je Ausgabespalte einzeln.
    # Beide Felder sind für Reiter 1 und 2 immer leer (Standard-Default).
    row_color: str | None = None
    cell_colors: list[str | None] = field(default_factory=list)


@dataclass
class ExportPayload:
    columns: list[ExportColumn]
    rows: list[ExportRow]
    header: ExportHeaderConfig
    font_size: int
    alternate_row_colors: bool
    separator_height_px: int
    filename_stem: str
    landscape: bool = False
    row_height_px: int = 20
    header_font_size: int = 10
    header_row_height_px: int = 20
    word_wrap: bool = True
    min_font_size: int = 5
