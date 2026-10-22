"""Zentrale Einheiten-Konvertierung: UI-Pixel <-> Excel-Spaltenbreite <-> Punkte (PDF).

Da Spaltenbreiten in der UI in Pixel vorgegeben sind, Excel-Spaltenbreiten
aber in "Zeichenbreiten" (bezogen auf die Standardschrift) und reportlab in
Punkten arbeitet, gibt es genau eine Stelle für diese Umrechnung - siehe
DESIGN.md Abschnitt 6.3. Die Excel-Formel ist eine verbreitete Näherung
(Calibri 11) und daher nicht pixelgenau, aber konsistent über die ganze
Anwendung.
"""
from __future__ import annotations

PX_PER_POINT = 96 / 72  # 96 DPI Bildschirmauflösung, 72 Punkte pro Zoll


def px_to_points(px: float) -> float:
    return px / PX_PER_POINT


def points_to_px(points: float) -> float:
    return points * PX_PER_POINT


def px_to_excel_width(px: float) -> float:
    """Näherungsformel für Calibri 11 (gängige Heuristik, siehe openpyxl-Dokumentation)."""
    return round(max((px - 5) / 7, 1.0), 2)


def excel_width_to_px(width: float) -> float:
    return round(width * 7 + 5)
