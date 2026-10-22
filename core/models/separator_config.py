"""Konfiguration der Trennzeilen zwischen Wertegruppen einer Spalte."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass
class SeparatorConfig:
    enabled: bool = False
    column: str | None = None
    height_px: int = 10
