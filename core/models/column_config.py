"""Konfiguration je Spalte: Suchspalte/Ausgabespalte-Auswahl, Reihenfolge, Breite."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass
class ColumnConfig:
    name: str
    search_enabled: bool = False
    output_enabled: bool = False
    output_order: int = 0
    width_px: int = 120
    # Nur zur Laufzeit: alternativer Anzeigename (z. B. für virtuelle Farbspalten).
    # Wird NICHT serialisiert.
    display_name: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "search_enabled": self.search_enabled,
            "output_enabled": self.output_enabled,
            "output_order": self.output_order,
            "width_px": self.width_px,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ColumnConfig":
        return cls(
            name=str(data["name"]),
            search_enabled=bool(data.get("search_enabled", False)),
            output_enabled=bool(data.get("output_enabled", False)),
            output_order=int(data.get("output_order", 0)),
            width_px=int(data.get("width_px", 120)),
        )
