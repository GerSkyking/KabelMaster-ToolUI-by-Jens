"""Zustandslose Such-Engine, gemeinsam genutzt von Reiter 1 (Einzelne Suche)
und Reiter 2 (Stapelsuche) - es gibt keine zweite Such-Implementierung.
"""
from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from core.models.search_options import SearchOptions


@dataclass
class SearchResult:
    matched_indices: list[int]
    total_matches: int


def stringify_cell(value: object) -> str:
    """Wandelt einen Zellwert in einen Anzeige-String um, NaN/None werden zu leerem String.

    Öffentlich, da auch der Export-Payload-Builder (core/export) dieselbe
    Stringifizierung benötigt, um z. B. Trennzeilen-Spaltenwerte zu vergleichen.
    """
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return ""
    return str(value)


class SearchEngine:
    """Führt Enthält-Suchen über eine oder mehrere Spalten eines DataFrames aus."""

    def search(self, dataframe: pd.DataFrame, options: SearchOptions) -> SearchResult:
        if not options.search_columns or len(options.term) < options.min_chars:
            return SearchResult(matched_indices=[], total_matches=0)

        mask = self._build_mask(dataframe, options.search_columns, options.term, options.case_insensitive)
        matched = dataframe.index[mask].tolist()
        return SearchResult(matched_indices=matched, total_matches=len(matched))

    def find_matches_with_actual_values(
        self,
        dataframe: pd.DataFrame,
        columns: list[str],
        term: str,
        case_insensitive: bool = True,
    ) -> tuple[pd.DataFrame, dict[int, list[str]]]:
        """Liefert Treffer-Zeilen sowie je Zeile die tatsächlich getroffenen Zellwerte.

        Wird für die Ergebnis-Spalte der Stapelsuche benötigt: bei Suchbegriff
        "X1" und Zellinhalt "X123" muss das Ergebnis "X123" enthalten, nicht "X1".
        """
        mask = self._build_mask(dataframe, columns, term, case_insensitive)
        matched_df = dataframe.loc[mask]

        needle = term.lower() if case_insensitive else term
        match_values: dict[int, list[str]] = {}
        for idx, row in matched_df.iterrows():
            values: list[str] = []
            for column in columns:
                cell_str = stringify_cell(row[column])
                haystack = cell_str.lower() if case_insensitive else cell_str
                if needle in haystack:
                    values.append(cell_str)
            match_values[idx] = values

        return matched_df, match_values

    def find_matched_columns(
        self,
        dataframe: pd.DataFrame,
        search_columns: list[str],
        term: str,
        case_insensitive: bool = True,
    ) -> dict[int, list[str]]:
        """Gibt je Trefferzeile die Liste der Spalten zurück, in denen der Begriff gefunden wurde.

        Wird von HighlightPayloadBuilder benötigt, um zellengenau färben zu können.
        """
        mask = self._build_mask(dataframe, search_columns, term, case_insensitive)
        matched_df = dataframe.loc[mask]
        needle = term.lower() if case_insensitive else term
        result: dict[int, list[str]] = {}
        for idx, row in matched_df.iterrows():
            matched_cols: list[str] = []
            for col in search_columns:
                cell_str = stringify_cell(row[col])
                haystack = cell_str.lower() if case_insensitive else cell_str
                if needle in haystack:
                    matched_cols.append(col)
            result[int(idx)] = matched_cols
        return result

    @staticmethod
    def _build_mask(
        dataframe: pd.DataFrame,
        columns: list[str],
        term: str,
        case_insensitive: bool,
    ) -> pd.Series:
        needle = term.lower() if case_insensitive else term
        mask = pd.Series(False, index=dataframe.index)
        for column in columns:
            stringified = dataframe[column].map(stringify_cell)
            if case_insensitive:
                stringified = stringified.str.lower()
            mask = mask | stringified.str.contains(needle, regex=False, na=False)
        return mask
