"""Kopfzeilen-Inhalte für Exporte: feste Zuordnung gemäß Anforderung.

Links: Ersteller, Firma
Mitte: Ort, Projekt/Funktion, Ergebnisname
Rechts: Datum

Deaktivierte globale Felder (enabled=False) werden nicht in die Kopfzeile
übernommen, ihr Wert bleibt aber in den Settings gespeichert.
"""
from __future__ import annotations

from dataclasses import dataclass

from core.models.global_fields import GlobalSettings


@dataclass
class ExportHeaderConfig:
    left: list[str]
    center: list[str]
    right: list[str]


def build_export_header(global_settings: GlobalSettings, result_name: str) -> ExportHeaderConfig:
    left = [
        field.value
        for field in (global_settings.creator, global_settings.company)
        if field.enabled and field.value
    ]
    center = [
        field.value
        for field in (global_settings.location, global_settings.project)
        if field.enabled and field.value
    ]
    if result_name:
        center.append(result_name)
    right = (
        [global_settings.date.value]
        if global_settings.date.enabled and global_settings.date.value
        else []
    )
    return ExportHeaderConfig(left=left, center=center, right=right)
