"""Excel-Import: liest .xlsx/.xls in ein LoadedDocument.

Engine-Auswahl:
* .xlsx -> openpyxl
* .xls  -> xlrd (Legacy-Format mit hartem Zeilenlimit von 65.536)

Die erste Zeile der Datei wird als Spaltennamen interpretiert (pandas-Standard
header=0). Leere oder doppelte Spaltennamen werden normalisiert, damit
nachfolgende Komponenten (Suche, Export, Vorlagen-Matching) sich auf
eindeutige, nicht-leere Spaltennamen verlassen können.
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd

from core.models.loaded_document import LoadedDocument

XLS_MAX_ROWS = 65536
SUPPORTED_EXTENSIONS = {".xlsx", ".xls"}


class ExcelImportError(Exception):
    """Basisklasse für alle Fehler beim Excel-Import."""


class UnsupportedFileTypeError(ExcelImportError):
    def __init__(self, path: Path) -> None:
        super().__init__(
            f"Dateityp '{path.suffix}' wird nicht unterstützt. "
            f"Unterstützt werden: {', '.join(sorted(SUPPORTED_EXTENSIONS))}."
        )
        self.path = path


class FileNotFoundImportError(ExcelImportError):
    def __init__(self, path: Path) -> None:
        super().__init__(f"Die Datei '{path}' wurde nicht gefunden.")
        self.path = path


class FileTooLargeError(ExcelImportError):
    def __init__(self, path: Path, row_count: int, limit: int) -> None:
        super().__init__(
            f"Die Datei '{path.name}' enthält {row_count} Zeilen und überschreitet damit "
            f"das Limit von {limit} Zeilen für das .xls-Format. "
            f"Bitte als .xlsx speichern und erneut importieren."
        )
        self.path = path
        self.row_count = row_count
        self.limit = limit


class EmptyFileError(ExcelImportError):
    def __init__(self, path: Path) -> None:
        super().__init__(f"Die Datei '{path.name}' enthält keine Spaltenüberschriften.")
        self.path = path


class ExcelReadError(ExcelImportError):
    def __init__(self, path: Path, original_error: Exception) -> None:
        super().__init__(f"Die Datei '{path.name}' konnte nicht gelesen werden: {original_error}")
        self.path = path
        self.original_error = original_error


def _engine_for(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix == ".xlsx":
        return "openpyxl"
    if suffix == ".xls":
        return "xlrd"
    raise UnsupportedFileTypeError(path)


def _normalize_columns(raw_columns: list) -> list[str]:
    seen: dict[str, int] = {}
    normalized: list[str] = []
    for index, raw_name in enumerate(raw_columns):
        name = str(raw_name).strip() if raw_name is not None else ""
        if name == "" or name.lower().startswith("unnamed:"):
            name = f"Spalte {index + 1}"
        if name in seen:
            seen[name] += 1
            name = f"{name} ({seen[name]})"
        else:
            seen[name] = 0
        normalized.append(name)
    return normalized


class ExcelReader:
    """Liest .xlsx- und .xls-Dateien in ein LoadedDocument."""

    def load(self, path: str | Path) -> LoadedDocument:
        path = Path(path)
        if not path.exists():
            raise FileNotFoundImportError(path)

        engine = _engine_for(path)

        try:
            dataframe = pd.read_excel(path, header=0, engine=engine, dtype=object)
        except Exception as exc:  # pandas/openpyxl/xlrd werfen diverse Fehlertypen
            raise ExcelReadError(path, exc) from exc

        if dataframe.shape[1] == 0:
            raise EmptyFileError(path)

        if engine == "xlrd" and len(dataframe) > XLS_MAX_ROWS:
            raise FileTooLargeError(path, len(dataframe), XLS_MAX_ROWS)

        dataframe.columns = _normalize_columns(list(dataframe.columns))

        return LoadedDocument(
            path=path,
            dataframe=dataframe,
            columns=list(dataframe.columns),
        )
