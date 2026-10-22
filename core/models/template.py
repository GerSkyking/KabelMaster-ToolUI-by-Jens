"""Vorlage: gespeicherte Spalten-/Sortier-/Trennzeilen-/Anzeige-/Exportkonfiguration.

column_names hält die Spaltennamen der Quelldatei zum Speicherzeitpunkt - das
ist die Grundlage für den exakten Abgleich beim automatischen Anwenden einer
Vorlage auf eine neu geladene Datei (siehe DESIGN.md, Abschnitt 8).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from core.models.batch_search import BatchSearchTerm
from core.models.color_models import ColorColumn, ColorDefinition, ColorSearchTerm
from core.models.column_config import ColumnConfig
from core.models.kmk_models import KmkConfig
from core.models.display_config import DisplayConfig
from core.models.separator_config import SeparatorConfig
from core.models.sort_config import SortConfig

CURRENT_TEMPLATE_SCHEMA_VERSION = 1


@dataclass
class Template:
    name: str
    column_names: list[str]
    columns: list[ColumnConfig]
    sort: SortConfig
    separator: SeparatorConfig
    display: DisplayConfig
    export_options: dict[str, Any] = field(default_factory=dict)
    schema_version: int = CURRENT_TEMPLATE_SCHEMA_VERSION
    # Reiter-Zugehörigkeit (leer = alle Reiter, für Altvorlagen-Kompatibilität)
    tab_id: str = ""
    # Reiter 2: Suchbegriffe der Stapelsuche
    batch_search_terms: list[BatchSearchTerm] = field(default_factory=list)
    # Reiter 3: Farbdefinitionen, Farbspalten, Suchbegriffe und Mindestanzahl für Zeilenmarkierung
    colors: list[ColorDefinition] = field(default_factory=list)
    color_columns: list[ColorColumn] = field(default_factory=list)
    color_search_terms: list[ColorSearchTerm] = field(default_factory=list)
    color_min_matches: int = 2
    # Reiter 4: KMK-Konfiguration (Typ + Beschrifter-Spalten)
    kmk_config: KmkConfig = field(default_factory=KmkConfig)
    # Reiter 5: Schrank-Erkennung (Muster-Auswahl, Schrank-Spalte); Suchbegriffe entfallen dort
    cabinet_config: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": CURRENT_TEMPLATE_SCHEMA_VERSION,
            "name": self.name,
            "tab_id": self.tab_id,
            "column_names": self.column_names,
            "columns": [column.to_dict() for column in self.columns],
            "sort": {"column": self.sort.column, "ascending": self.sort.ascending},
            "separator": {
                "enabled": self.separator.enabled,
                "column": self.separator.column,
                "height_px": self.separator.height_px,
            },
            "display": {
                "font_size": self.display.font_size,
                "alternate_row_colors": self.display.alternate_row_colors,
                "landscape": self.display.landscape,
                "row_height_px": self.display.row_height_px,
                "header_font_size": self.display.header_font_size,
                "header_row_height_px": self.display.header_row_height_px,
                "word_wrap": self.display.word_wrap,
                "min_font_size": self.display.min_font_size,
            },
            "export_options": self.export_options,
            "batch_search_terms": [{"term": t.term, "enabled": t.enabled} for t in self.batch_search_terms],
            "colors": [c.to_dict() for c in self.colors],
            "color_columns": [cc.to_dict() for cc in self.color_columns],
            "color_search_terms": [t.to_dict() for t in self.color_search_terms],
            "color_min_matches": self.color_min_matches,
            "kmk_config": self.kmk_config.to_dict(),
            "cabinet_config": self.cabinet_config,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Template":
        sort_data = data.get("sort") or {}
        separator_data = data.get("separator") or {}
        display_data = data.get("display") or {}
        return cls(
            name=str(data["name"]),
            tab_id=str(data.get("tab_id", "")),
            column_names=list(data.get("column_names", [])),
            columns=[ColumnConfig.from_dict(item) for item in data.get("columns", [])],
            sort=SortConfig(
                column=sort_data.get("column"),
                ascending=bool(sort_data.get("ascending", True)),
            ),
            separator=SeparatorConfig(
                enabled=bool(separator_data.get("enabled", False)),
                column=separator_data.get("column"),
                height_px=int(separator_data.get("height_px", 10)),
            ),
            display=DisplayConfig(
                font_size=int(display_data.get("font_size", 10)),
                alternate_row_colors=bool(display_data.get("alternate_row_colors", False)),
                landscape=bool(display_data.get("landscape", False)),
                row_height_px=int(display_data.get("row_height_px", 20)),
                header_font_size=int(display_data.get("header_font_size", 10)),
                header_row_height_px=int(display_data.get("header_row_height_px", 20)),
                word_wrap=bool(display_data.get("word_wrap", True)),
                min_font_size=int(display_data.get("min_font_size", 5)),
            ),
            export_options=dict(data.get("export_options", {})),
            schema_version=CURRENT_TEMPLATE_SCHEMA_VERSION,
            batch_search_terms=[
                BatchSearchTerm(term=str(t.get("term", "")), enabled=bool(t.get("enabled", True)))
                for t in data.get("batch_search_terms", [])
            ],
            colors=[ColorDefinition.from_dict(c) for c in data.get("colors", [])],
            color_columns=[ColorColumn.from_dict(cc) for cc in data.get("color_columns", [])],
            color_search_terms=[ColorSearchTerm.from_dict(t) for t in data.get("color_search_terms", [])],
            color_min_matches=int(data.get("color_min_matches", 2)),
            kmk_config=KmkConfig.from_dict(data.get("kmk_config", {})),
            cabinet_config=dict(data.get("cabinet_config") or {}),
        )
