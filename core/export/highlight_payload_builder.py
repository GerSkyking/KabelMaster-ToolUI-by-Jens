"""Baut ein ExportPayload mit farblicher Markierung für Reiter 3 (Farbmarkierung).

Die komplette Ursprungstabelle bleibt sichtbar (kein Filtern).
Trefferzellen werden mit der aufgelösten Farbe ihres Suchbegriffs markiert.
Erreicht eine Farb-ID in einer Zeile mindestens min_matches Treffer, erhält die gesamte
Zeile diese Hintergrundfarbe (Phase 2). Andernfalls werden nur die Trefferzellen
eingefärbt (Phase 1).

Virtuelle Farbspalten (cc_col_ids: dict[internalKey→cc_id]) werden wie echte
Ausgabespalten in output_cols eingetragen, lesen aber keine Daten aus dem Dataframe,
sondern berechnen ihren Wert aus der Farbzuordnung der Zeile.
"""
from __future__ import annotations

from collections import Counter

import pandas as pd

from core.color.color_manager import ColorManager
from core.models.color_models import ColorSearchTerm
from core.models.column_config import ColumnConfig
from core.models.display_config import DisplayConfig
from core.models.export_header_config import ExportHeaderConfig
from core.models.export_payload import ExportColumn, ExportPayload, ExportRow
from core.models.separator_config import SeparatorConfig
from core.models.sort_config import SortConfig
from core.search.search_engine import SearchEngine, stringify_cell


class HighlightPayloadBuilder:
    """Erstellt ein ExportPayload mit Zell- und Zeilenfärbung aus ColorSearchTermen."""

    def __init__(self) -> None:
        self._search_engine = SearchEngine()

    def build(
        self,
        dataframe: pd.DataFrame,
        columns: list[ColumnConfig],
        color_terms: list[ColorSearchTerm],
        color_manager: ColorManager,
        sort_config: SortConfig,
        separator_config: SeparatorConfig,
        display_config: DisplayConfig,
        header: ExportHeaderConfig,
        filename_stem: str,
        min_matches: int = 2,
        cc_col_ids: dict[str, int] | None = None,
    ) -> ExportPayload | None:
        """Baut das ExportPayload.

        cc_col_ids: Mapping interner Schlüssel → ColorColumn-ID für virtuelle Farbspalten.
        Diese Spalten erscheinen in der Ausgabe, lesen aber aus der Farbzuordnung, nicht
        aus dem Dataframe.
        """
        virtual_keys: set[str] = set(cc_col_ids or {})

        active_terms = [t for t in color_terms if t.enabled and t.term.strip()]
        # Suchspalten sind nur echte Datenspalten
        search_cols = [c.name for c in columns if c.search_enabled and c.name not in virtual_keys]

        output_cols = sorted(
            (c for c in columns if c.output_enabled),
            key=lambda c: c.output_order,
        )
        if not output_cols:
            return None

        # Export-Spalten: display_name oder interner name als Spaltenkopf
        export_columns = [
            ExportColumn(name=c.display_name or c.name, width_px=c.width_px)
            for c in output_cols
        ]

        # Schritt 1: Für jede (Zeile, echte Spalte) die zugeordnete Farb-ID ermitteln.
        cell_color_map: dict[tuple[int, str], int] = {}
        if active_terms and search_cols:
            for color_term in active_terms:
                matched = self._search_engine.find_matched_columns(
                    dataframe, search_cols, color_term.term, case_insensitive=True
                )
                for row_idx, matched_cols in matched.items():
                    for col_name in matched_cols:
                        cell_color_map[(row_idx, col_name)] = color_term.color_id

        # Schritt 2: Sortierung auf der vollständigen Tabelle anwenden
        selected = self._apply_sort(dataframe, sort_config)

        # Namen der echten Ausgabespalten (ohne virtuelle)
        data_output_names = [c.name for c in output_cols if c.name not in virtual_keys]

        # Schritt 3: Alle Zeilen mit optionaler Farbinformation aufbauen
        rows: list[ExportRow] = []
        previous_sep_value: str | None = None
        use_separator = bool(separator_config.enabled and separator_config.column in selected.columns)
        sep_col_count = len(output_cols)

        for idx, row_data in selected.iterrows():
            row_idx = int(idx)

            if use_separator:
                current_value = stringify_cell(row_data[separator_config.column])
                if previous_sep_value is not None and current_value != previous_sep_value:
                    rows.append(ExportRow(values=[""] * sep_col_count, is_separator=True))
                previous_sep_value = current_value

            # Farb-IDs für echte Ausgabespalten dieser Zeile
            col_color_ids: dict[str, int] = {
                col: cell_color_map[(row_idx, col)]
                for col in data_output_names
                if (row_idx, col) in cell_color_map
            }

            # Phase 2: Zeilenmarkierung, wenn eine Farb-ID min_matches erreicht
            color_id_counts: Counter[int] = Counter(col_color_ids.values())
            dominant_color_id: int | None = None
            for color_id, count in color_id_counts.most_common():
                if count >= min_matches:
                    dominant_color_id = color_id
                    break

            # Werte für alle Ausgabespalten (echt + virtuell) in Reihenfolge
            values: list[str] = []
            for col_cfg in output_cols:
                if col_cfg.name in virtual_keys:
                    # Virtuell: Wert aus Farbzuordnung berechnen
                    cc_id = (cc_col_ids or {}).get(col_cfg.name)
                    col_val = ""
                    if cc_id is not None:
                        cc = color_manager.get_column(cc_id)
                        if cc is not None:
                            if dominant_color_id is not None:
                                dom_def = color_manager.get(dominant_color_id)
                                if dom_def and dom_def.column_id == cc.id:
                                    col_val = dom_def.name
                            else:
                                for _, c_id in col_color_ids.items():
                                    c_def = color_manager.get(c_id)
                                    if c_def and c_def.column_id == cc.id:
                                        col_val = c_def.name
                                        break
                    values.append(col_val)
                else:
                    values.append(stringify_cell(row_data[col_cfg.name]))

            if dominant_color_id is not None:
                row_color = color_manager.resolve_display_hex(dominant_color_id)
                rows.append(ExportRow(values=values, row_color=row_color))
            else:
                cell_colors: list[str | None] = [
                    color_manager.resolve_display_hex(col_color_ids[col_cfg.name])
                    if col_cfg.name in col_color_ids
                    else None
                    for col_cfg in output_cols
                ]
                rows.append(ExportRow(values=values, cell_colors=cell_colors))

        return ExportPayload(
            columns=export_columns,
            rows=rows,
            header=header,
            font_size=display_config.font_size,
            alternate_row_colors=display_config.alternate_row_colors,
            separator_height_px=separator_config.height_px,
            filename_stem=filename_stem,
            landscape=display_config.landscape,
            row_height_px=display_config.row_height_px,
            header_font_size=display_config.header_font_size,
            header_row_height_px=display_config.header_row_height_px,
            word_wrap=display_config.word_wrap,
            min_font_size=display_config.min_font_size,
        )

    @staticmethod
    def _apply_sort(dataframe: pd.DataFrame, sort_config: SortConfig) -> pd.DataFrame:
        if not sort_config.column or sort_config.column not in dataframe.columns:
            return dataframe
        sort_key = dataframe[sort_config.column].map(stringify_cell)
        return (
            dataframe.assign(_sort_key=sort_key)
            .sort_values("_sort_key", ascending=sort_config.ascending, kind="stable")
            .drop(columns="_sort_key")
        )
