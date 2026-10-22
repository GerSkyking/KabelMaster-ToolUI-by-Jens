"""Baut Beschrifter-Gruppen aus Such-Ergebnissen für Reiter 4 (KMK).

Logik:
- Jeder aktive Suchbegriff erzeugt eine Gruppe.
- Zeilen, die genau von einem Begriff getroffen werden, landen zusätzlich in RESTE.
- Zeilen, die von zwei oder mehr Begriffen getroffen werden, erscheinen nur in
  ihren jeweiligen Gruppen (kein RESTE-Eintrag).
- Duplikat-Deckel: max. 2 Beschrifter mit identischem Zeileninhalt insgesamt.
"""
from __future__ import annotations

from collections import Counter

import pandas as pd

from core.models.batch_search import BatchSearchTerm
from core.models.kmk_models import KmkGroup, KmkLabel
from core.models.search_options import SearchOptions
from core.search.search_engine import SearchEngine, stringify_cell

_RESTE_TITLE = "RESTE"
_MAX_DUPLICATES = 2


class KmkLabelBuilder:
    """Erstellt geordnete Gruppen von KmkLabeln aus Suchbegriffen und einem DataFrame."""

    def __init__(self) -> None:
        self._engine = SearchEngine()

    def build_groups(
        self,
        dataframe: pd.DataFrame,
        search_columns: list[str],
        terms: list[BatchSearchTerm],
        label_column_names: list[str],
    ) -> list[KmkGroup]:
        """Gibt geordnete Gruppen (inklusive RESTE) zurück."""
        active_terms = [t for t in terms if t.enabled and t.term.strip()]
        if not active_terms or not search_columns or not label_column_names:
            return []

        # Schritt 1: Pro Begriff Treffer-Indizes ermitteln
        term_to_indices: dict[str, list[int]] = {}
        for term in active_terms:
            options = SearchOptions(
                search_columns=search_columns,
                term=term.term,
                case_insensitive=True,
                min_chars=1,
            )
            result = self._engine.search(dataframe, options)
            term_to_indices[term.term] = result.matched_indices

        # Schritt 2: Zählen, wie viele Begriffe jede Zeile getroffen haben
        row_hit_count: Counter[int] = Counter()
        for indices in term_to_indices.values():
            for idx in set(indices):
                row_hit_count[idx] += 1

        # Schritt 3: Hauptgruppen aufbauen
        groups: list[KmkGroup] = []
        for term in active_terms:
            indices = term_to_indices[term.term]
            labels = [
                self._make_label(dataframe, idx, label_column_names)
                for idx in indices
            ]
            if labels:
                groups.append(KmkGroup(title=term.term, labels=labels))

        # Schritt 4: RESTE – Zeilen, die exakt einmal getroffen wurden
        reste_indices = sorted(idx for idx, count in row_hit_count.items() if count == 1)
        if reste_indices:
            reste_labels = [
                self._make_label(dataframe, idx, label_column_names)
                for idx in reste_indices
            ]
            groups.append(KmkGroup(title=_RESTE_TITLE, labels=reste_labels))

        # Schritt 5: Duplikat-Deckel anwenden
        return self._apply_duplicate_cap(groups)

    @staticmethod
    def drop_reste(groups: list[KmkGroup]) -> list[KmkGroup]:
        """Entfernt die RESTE-Gruppe (für Anzeige/Export mit ausgeschalteter Checkbox)."""
        return [g for g in groups if g.title != _RESTE_TITLE]

    @staticmethod
    def _make_label(
        dataframe: pd.DataFrame, idx: int, column_names: list[str]
    ) -> KmkLabel:
        row = dataframe.loc[idx]
        lines = [
            stringify_cell(row[col])
            for col in column_names
            if col in dataframe.columns
        ]
        return KmkLabel(lines=lines, source_index=int(idx))

    @staticmethod
    def _apply_duplicate_cap(groups: list[KmkGroup]) -> list[KmkGroup]:
        """Begrenzt identische Beschrifter auf maximal _MAX_DUPLICATES Exemplare."""
        seen: Counter[tuple[str, ...]] = Counter()
        result: list[KmkGroup] = []
        for group in groups:
            kept: list[KmkLabel] = []
            for label in group.labels:
                key = tuple(label.lines)
                if seen[key] < _MAX_DUPLICATES:
                    kept.append(label)
                    seen[key] += 1
            if kept:
                result.append(KmkGroup(title=group.title, labels=kept))
        return result
