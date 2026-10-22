"""Verwaltung von Farbdefinitionen: Hinzufügen, Bearbeiten, Löschen, Farbauflösung.

Die Klasse ist zustandsbehaftet und wird je Reiter-Instanz gehalten. Serialisierung
erfolgt über to_list/from_list, damit die Daten in AppSettings.tabs und Vorlagen
persistiert werden können.
"""
from __future__ import annotations

from core.models.color_models import ColorColumn, ColorDefinition


def blend_with_white(color_hex: str, alpha: int) -> str:
    """Mischt eine Farbe mit Weiß entsprechend der Transparenz.

    alpha=0  → vollständig deckend (Originalfarbe)
    alpha=100 → vollständig transparent (Weiß)
    Wird für Qt-Vorschau, XLSX und PDF einheitlich verwendet.
    """
    hex_clean = color_hex.lstrip("#")
    r = int(hex_clean[0:2], 16)
    g = int(hex_clean[2:4], 16)
    b = int(hex_clean[4:6], 16)
    factor = 1.0 - alpha / 100.0
    r2 = round(r * factor + 255 * (1.0 - factor))
    g2 = round(g * factor + 255 * (1.0 - factor))
    b2 = round(b * factor + 255 * (1.0 - factor))
    return f"#{r2:02X}{g2:02X}{b2:02X}"


class ColorManager:
    """Verwaltet eine geordnete Liste von Farbdefinitionen mit auto-inkrementeller ID."""

    DEFAULT_COLORS: list[tuple[str, str, int]] = [
        ("Gelb", "#FFFF00", 30),
        ("Rot", "#FF0000", 50),
        ("Grün", "#00FF00", 20),
    ]

    def __init__(
        self,
        definitions: list[ColorDefinition] | None = None,
        color_columns: list[ColorColumn] | None = None,
    ) -> None:
        self._definitions: list[ColorDefinition] = list(definitions or [])
        self._next_id = max((d.id for d in self._definitions), default=0) + 1
        self._color_columns: list[ColorColumn] = list(color_columns or [])
        self._next_col_id = max((c.id for c in self._color_columns), default=0) + 1

    @classmethod
    def create_default(cls) -> "ColorManager":
        manager = cls()
        for name, hex_color, alpha in cls.DEFAULT_COLORS:
            manager.add(name, hex_color, alpha)
        return manager

    # ---- Spalten-Verwaltung ----

    def add_column(self, name: str, width_px: int = 100) -> ColorColumn:
        col = ColorColumn(id=self._next_col_id, name=name, width_px=width_px)
        self._color_columns.append(col)
        self._next_col_id += 1
        return col

    def update_column(self, column_id: int, name: str, width_px: int) -> None:
        for col in self._color_columns:
            if col.id == column_id:
                col.name = name
                col.width_px = width_px
                return

    def remove_column(self, column_id: int) -> None:
        self._color_columns = [c for c in self._color_columns if c.id != column_id]
        for d in self._definitions:
            if d.column_id == column_id:
                d.column_id = None

    def get_column(self, column_id: int) -> ColorColumn | None:
        for col in self._color_columns:
            if col.id == column_id:
                return col
        return None

    def all_columns(self) -> list[ColorColumn]:
        return list(self._color_columns)

    def columns_to_list(self) -> list[dict]:
        return [c.to_dict() for c in self._color_columns]

    # ---- Farb-Verwaltung ----

    def add(self, name: str, color_hex: str, alpha: int = 30) -> ColorDefinition:
        definition = ColorDefinition(id=self._next_id, name=name, color_hex=color_hex, alpha=alpha)
        self._definitions.append(definition)
        self._next_id += 1
        return definition

    def update(self, color_id: int, name: str, color_hex: str, alpha: int) -> None:
        for definition in self._definitions:
            if definition.id == color_id:
                definition.name = name
                definition.color_hex = color_hex
                definition.alpha = alpha
                return

    def remove(self, color_id: int) -> None:
        self._definitions = [d for d in self._definitions if d.id != color_id]

    def get(self, color_id: int) -> ColorDefinition | None:
        for definition in self._definitions:
            if definition.id == color_id:
                return definition
        return None

    def all(self) -> list[ColorDefinition]:
        return list(self._definitions)

    def resolve_display_hex(self, color_id: int) -> str | None:
        """Gibt den vorgeblendeten Hex-Farbwert zurück (mit Weiß gemischt)."""
        definition = self.get(color_id)
        if definition is None:
            return None
        return blend_with_white(definition.color_hex, definition.alpha)

    def to_list(self) -> list[dict]:
        return [d.to_dict() for d in self._definitions]

    @classmethod
    def from_list(
        cls, data: list[dict], columns_data: list[dict] | None = None
    ) -> "ColorManager":
        definitions = [ColorDefinition.from_dict(item) for item in data]
        columns = [ColorColumn.from_dict(item) for item in (columns_data or [])]
        return cls(definitions, columns)
