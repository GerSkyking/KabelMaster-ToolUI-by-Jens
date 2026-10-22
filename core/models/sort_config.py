"""Sortierkonfiguration: eine Sortierspalte, auf- oder absteigend."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass
class SortConfig:
    column: str | None = None
    ascending: bool = True
