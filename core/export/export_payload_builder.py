"""Baut ein ExportPayload aus Dokument-Daten und UI-Konfiguration.

Einzige Stelle, an der Sortierung, Trennzeilen-Einfügung und
Spaltenauswahl/-reihenfolge final aufgelöst werden - XlsxExporter und
PdfExporter konsumieren ausschließlich das Ergebnis (siehe DESIGN.md, 6.1).
"""
from __future__ import annotations

import pandas as pd

from core.models.column_config import ColumnConfig
from core.models.display_config import DisplayConfig
from core.models.export_header_config import ExportHeaderConfig
from core.models.export_payload import ExportColumn, ExportPayload, ExportRow
from core.models.separator_config import SeparatorConfig
from core.models.sort_config import SortConfig
from core.search.search_engine import stringify_cell


class ExportPayloadBuilder:
    def build(
        self,
        dataframe: pd.DataFrame,
        row_indices: list[int] | None,
        columns: list[ColumnConfig],
        sort_config: SortConfig,
        separator_config: SeparatorConfig,
        display_config: DisplayConfig,
        header: ExportHeaderConfig,
        filename_stem: str,
    ) -> ExportPayload:
        selected = dataframe.loc[row_indices] if row_indices is not None else dataframe
        selected = self._apply_sort(selected, sort_config)

        output_columns = sorted(
            (column for column in columns if column.output_enabled),
            key=lambda column: column.output_order,
        )

        rows = self._build_rows(selected, output_columns, separator_config)
        export_columns = [ExportColumn(name=c.name, width_px=c.width_px) for c in output_columns]

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
        # Stringbasierte Sortierung: Spalten sind dtype=object (gemischte Excel-Werte),
        # ein direkter Vergleich könnte bei gemischten Typen einen TypeError auslösen.
        sort_key = dataframe[sort_config.column].map(stringify_cell)
        return (
            dataframe.assign(_sort_key=sort_key)
            .sort_values("_sort_key", ascending=sort_config.ascending, kind="stable")
            .drop(columns="_sort_key")
        )

    @staticmethod
    def _build_rows(
        dataframe: pd.DataFrame,
        output_columns: list[ColumnConfig],
        separator_config: SeparatorConfig,
    ) -> list[ExportRow]:
        rows: list[ExportRow] = []
        previous_value: str | None = None
        use_separator = bool(separator_config.enabled and separator_config.column in dataframe.columns)

        for _, row in dataframe.iterrows():
            if use_separator:
                current_value = stringify_cell(row[separator_config.column])
                if previous_value is not None and current_value != previous_value:
                    rows.append(ExportRow(values=[""] * len(output_columns), is_separator=True))
                previous_value = current_value

            values = [stringify_cell(row[column.name]) for column in output_columns]
            rows.append(ExportRow(values=values, is_separator=False))

        return rows
