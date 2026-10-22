"""Konfiguration der Stapelsuche: verwaltbare Liste von Suchbegriffen + Ergebnis-Spalte."""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class BatchSearchTerm:
    term: str
    enabled: bool = True


@dataclass
class BatchSearchConfig:
    terms: list[BatchSearchTerm] = field(default_factory=list)
    result_column_enabled: bool = False
    result_column_name: str = "Ergebnis"
    separator: str = "*"
