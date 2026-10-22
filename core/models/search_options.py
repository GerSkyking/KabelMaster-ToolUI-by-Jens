"""Parameter für eine Suchausführung."""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class SearchOptions:
    search_columns: list[str] = field(default_factory=list)
    term: str = ""
    case_insensitive: bool = True
    live_search: bool = True
    min_chars: int = 3
