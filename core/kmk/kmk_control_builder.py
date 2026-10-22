"""Baut die Excel-Kontrolldatei zur KMK-PDF: gleiche Reihenfolge wie die Beschrifter im PDF.

Je Gruppe (Suchbegriff / RESTE) gibt es - sofern die Gruppenüberschrift nicht
ausgeblendet ist - eine hervorgehobene Überschriftszeile, danach je Beschrifter
genau eine Tabellenzeile der Quelldatei. Duplikat-Deckel und RESTE entsprechen
damit exakt dem, was im PDF steht.
"""
from __future__ import annotations

import pandas as pd

from core.export.export_payload_builder import ExportPayloadBuilder
from core.models.column_config import ColumnConfig
from core.models.display_config import DisplayConfig
from core.models.export_header_config import ExportHeaderConfig
from core.models.export_payload import ExportPayload, ExportRow
from core.models.kmk_models import KmkGroup
from core.models.separator_config import SeparatorConfig
from core.models.sort_config import SortConfig

GROUP_ROW_COLOR = "#D3D3D3"


class KmkControlBuilder:
    def __init__(self) -> None:
        self._payload_builder = ExportPayloadBuilder()

    def build(
        self,
        dataframe: pd.DataFrame,
        groups: list[KmkGroup],
        columns: list[ColumnConfig],
        header: ExportHeaderConfig,
        filename_stem: str,
        header_mode: str = "first_field",
    ) -> ExportPayload:
        ordered_indices: list[int] = []
        group_sizes: list[int] = []
        for group in groups:
            indices = [label.source_index for label in group.labels if label.source_index is not None]
            ordered_indices.extend(indices)
            group_sizes.append(len(indices))

        payload = self._payload_builder.build(
            dataframe, ordered_indices, columns, SortConfig(), SeparatorConfig(),
            DisplayConfig(), header, filename_stem,
        )
        if header_mode == "hidden" or not payload.columns:
            return payload

        rows: list[ExportRow] = []
        cursor = 0
        for group, size in zip(groups, group_sizes):
            title = f"<< {group.title} ({len(group.labels)} Kabel) >>"
            rows.append(ExportRow(
                values=[title] + [""] * (len(payload.columns) - 1),
                row_color=GROUP_ROW_COLOR,
            ))
            rows.extend(payload.rows[cursor:cursor + size])
            cursor += size
        payload.rows = rows
        return payload
