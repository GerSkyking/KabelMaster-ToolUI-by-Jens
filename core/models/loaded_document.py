"""Repräsentation einer importierten Excel-Datei im Arbeitsspeicher."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

import pandas as pd


@dataclass
class LoadedDocument:
    path: Path
    dataframe: pd.DataFrame
    columns: list[str]
    loaded_at: datetime = field(default_factory=datetime.now)

    @property
    def row_count(self) -> int:
        return len(self.dataframe)

    @property
    def original_filename(self) -> str:
        return self.path.name

    @property
    def original_stem(self) -> str:
        """Originaldateiname ohne Erweiterung, z. B. für Export-Dateinamen."""
        return self.path.stem
