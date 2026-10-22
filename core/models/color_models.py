"""Farbdefinitionen und farbgebundene Suchbegriffe für Reiter 3 (Farbmarkierung)."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass
class ColorColumn:
    """Eine benannte Ausgabespalte, der Farben zugeordnet werden können."""

    id: int
    name: str
    width_px: int = 100

    def to_dict(self) -> dict[str, Any]:
        return {"id": self.id, "name": self.name, "width_px": self.width_px}

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ColorColumn":
        return cls(
            id=int(data["id"]),
            name=str(data["name"]),
            width_px=int(data.get("width_px", 100)),
        )


@dataclass
class ColorDefinition:
    """Eine benannte Farbe mit Transparenzgrad für die Zellenmarkierung."""

    id: int
    name: str
    color_hex: str  # z. B. "#FFFF00"
    alpha: int = 30  # 0 = vollständig deckend, 100 = vollständig transparent
    column_id: int | None = None  # Zugeordnete ColorColumn-ID (optional)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "color_hex": self.color_hex,
            "alpha": self.alpha,
            "column_id": self.column_id,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ColorDefinition":
        return cls(
            id=int(data["id"]),
            name=str(data["name"]),
            color_hex=str(data["color_hex"]),
            alpha=int(data.get("alpha", 30)),
            column_id=data.get("column_id"),
        )


@dataclass
class ColorSearchTerm:
    """Suchbegriff mit Referenz auf eine Farb-ID – keine direkte Farbspeicherung."""

    term: str
    enabled: bool = True
    color_id: int = 1

    def to_dict(self) -> dict[str, Any]:
        return {"term": self.term, "enabled": self.enabled, "color_id": self.color_id}

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ColorSearchTerm":
        return cls(
            term=str(data.get("term", "")),
            enabled=bool(data.get("enabled", True)),
            color_id=int(data.get("color_id", 1)),
        )
