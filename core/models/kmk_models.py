"""Datenmodelle für Reiter 4 (KMK – Kabelmarkierung / Beschrifter-Generator)."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

MM_TO_PT = 2.8346456692913385  # 1 mm in Punkte (72 pt/Zoll / 25.4 mm/Zoll)


@dataclass
class KmkType:
    """Beschreibt einen Beschrifter-Schildtyp mit physischen Abmessungen."""

    name: str = "KMK-2"
    height_mm: float = 8.0
    width_mm: float = 29.0

    @property
    def height_pt(self) -> float:
        return self.height_mm * MM_TO_PT

    @property
    def width_pt(self) -> float:
        return self.width_mm * MM_TO_PT

    def to_dict(self) -> dict[str, Any]:
        return {"name": self.name, "height_mm": self.height_mm, "width_mm": self.width_mm}

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "KmkType":
        return cls(
            name=str(data.get("name", "KMK-2")),
            height_mm=float(data.get("height_mm", 8.0)),
            width_mm=float(data.get("width_mm", 29.0)),
        )


@dataclass
class KmkLabel:
    """Ein einzelner Beschrifter: mehrere Textzeilen, optional als Gruppenüberschrift."""

    lines: list[str]
    is_header: bool = False
    overflow: bool = False  # wird vom PDF-Generator gesetzt
    source_index: int | None = None  # Zeilenindex im DataFrame (für Excel-Export)


@dataclass
class KmkGroup:
    """Eine Gruppe von Beschriftern, ausgelöst durch einen Suchbegriff."""

    title: str
    labels: list[KmkLabel]


_VALID_HEADER_MODES = {"own_row", "first_field", "hidden"}


@dataclass
class KmkConfig:
    """Vollständige Konfiguration für einen KMK-Exportvorgang."""

    kmk_type: KmkType = field(default_factory=KmkType)
    font_size_pt: float = 6.0
    frame_enabled: bool = True
    frame_width_pt: float = 0.5
    frame_color: str = "#000000"
    frame_padding_pt: float = 2.0
    label_column_names: list[str] = field(default_factory=list)
    # Layout-Optionen
    header_mode: str = "first_field"   # "own_row" | "first_field" | "hidden"
    seamless: bool = True              # Gruppen ohne künstliche Leerzeilen anfügen
    include_reste: bool = True         # RESTE-Gruppe anzeigen/exportieren
    auto_shrink: bool = True           # Text automatisch verkleinern, bis er passt
    min_font_size_pt: float = 3.0      # Untergrenze für die automatische Verkleinerung
    # Beschrifter-Inhalt komplett: {"order": [...], "enabled": {Spalte: bool}} (leer = nicht gespeichert)
    label_content: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "kmk_type": self.kmk_type.to_dict(),
            "font_size_pt": self.font_size_pt,
            "frame_enabled": self.frame_enabled,
            "frame_width_pt": self.frame_width_pt,
            "frame_color": self.frame_color,
            "frame_padding_pt": self.frame_padding_pt,
            "label_column_names": list(self.label_column_names),
            "header_mode": self.header_mode,
            "seamless": self.seamless,
            "include_reste": self.include_reste,
            "auto_shrink": self.auto_shrink,
            "min_font_size_pt": self.min_font_size_pt,
            "label_content": {
                "order": list(self.label_content.get("order", [])),
                "enabled": dict(self.label_content.get("enabled", {})),
            } if self.label_content else {},
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "KmkConfig":
        raw_mode = str(data.get("header_mode", "first_field"))
        header_mode = raw_mode if raw_mode in _VALID_HEADER_MODES else "first_field"
        return cls(
            kmk_type=KmkType.from_dict(data.get("kmk_type", {})),
            font_size_pt=float(data.get("font_size_pt", 6.0)),
            frame_enabled=bool(data.get("frame_enabled", True)),
            frame_width_pt=float(data.get("frame_width_pt", 0.5)),
            frame_color=str(data.get("frame_color", "#000000")),
            frame_padding_pt=float(data.get("frame_padding_pt", 2.0)),
            label_column_names=list(data.get("label_column_names", [])),
            header_mode=header_mode,
            seamless=bool(data.get("seamless", True)),
            include_reste=bool(data.get("include_reste", True)),
            auto_shrink=bool(data.get("auto_shrink", True)),
            min_font_size_pt=float(data.get("min_font_size_pt", 3.0)),
            label_content=dict(data.get("label_content") or {}),
        )
