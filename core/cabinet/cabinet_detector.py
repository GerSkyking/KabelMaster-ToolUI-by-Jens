"""Schrank-Erkennung für Reiter 5 mit frei baubaren Formaten.

Ein Format beschreibt, wie ein Schrank im Zelltext aussieht:

* ``X``  (groß)  = gesuchter Schrank (Ergebnis)
* ``x``  (klein) = Feld, wird angezeigt, wenn "Feld mit ausgeben" aktiv ist (z. B. E05)
* ``y``  (egal)  = wird ignoriert
* alle anderen Zeichen (``+ - = / .``, Ziffern, andere Buchstaben wie ``E00``) müssen genau so
  im Text stehen (Groß-/Kleinschreibung egal)

Aufeinanderfolgende gleiche Buchstaben bilden ein Segment aus Buchstaben, Ziffern und "_"
("xx" und "x" sind also gleich). Beispiele:

* ``xx+XX``      ``=E05+SC15-X130``  -> ``SC15``  bzw. mit Feld ``E05+SC15``
* ``-XX``        ``-SC15``           -> ``SC15``
* ``xx-yy+XX``   ``E05-K1+SC15``     -> ``SC15``  bzw. ``E05+SC15``
* ``E00+XX``     ``=E00+SC15``       -> ``SC15``  (nur Schränke im Feld E00)

Das Ergebnis mit Feld setzt die gezeigten Teile mit dem Trennzeichen zusammen, das im Format
unmittelbar vor dem jeweiligen Teil steht.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

import pandas as pd

from core.search.search_engine import stringify_cell

_SEG = r"[A-Za-z0-9_]+"
FIELD_LETTERS = ("E", "J", "H")


@dataclass(frozen=True)
class CabinetFormat:
    pattern: str
    enabled: bool = True
    with_field: bool = False  # gezeigte (x-)Teile vor den Schrank setzen

    def is_valid(self) -> bool:
        return "X" in self.pattern

    def to_dict(self) -> dict:
        return {"pattern": self.pattern, "enabled": self.enabled, "with_field": self.with_field}

    @classmethod
    def from_dict(cls, data: dict) -> "CabinetFormat":
        return cls(
            pattern=str(data.get("pattern", "")),
            enabled=bool(data.get("enabled", True)),
            with_field=bool(data.get("with_field", False)),
        )


DEFAULT_FORMATS = [
    CabinetFormat("+XX", enabled=True, with_field=False),
    CabinetFormat("xx+XX", enabled=False, with_field=True),
    CabinetFormat("xx-XX", enabled=False, with_field=True),
    CabinetFormat("-XX", enabled=False, with_field=False),
]


def formats_from_dicts(items: list | None) -> list[CabinetFormat]:
    if not items:
        return list(DEFAULT_FORMATS)
    return [CabinetFormat.from_dict(d) for d in items if isinstance(d, dict)]


def _natural_key(text: str) -> list:
    return [int(p) if p.isdigit() else p for p in re.split(r"(\d+)", text)]


@dataclass
class _Compiled:
    regex: re.Pattern
    # (Gruppenname, Art "show"/"search", Trennzeichen vor dem Teil)
    parts: list[tuple[str, str, str]] = field(default_factory=list)


_KIND_BY_CHAR = {"x": "show", "X": "search", "y": "skip", "Y": "skip"}
_compile_cache: dict[str, _Compiled] = {}


def _compile(pattern: str) -> _Compiled:
    cached = _compile_cache.get(pattern)
    if cached is not None:
        return cached
    regex_src: list[str] = []
    parts: list[tuple[str, str, str]] = []
    pending_literal = ""
    index = 0
    first_is_segment = pattern[:1] in _KIND_BY_CHAR
    last_is_segment = pattern[-1:] in _KIND_BY_CHAR
    while index < len(pattern):
        char = pattern[index]
        kind = _KIND_BY_CHAR.get(char)
        if kind is None:
            regex_src.append(re.escape(char))
            pending_literal += char
            index += 1
            continue
        end = index
        while end < len(pattern) and _KIND_BY_CHAR.get(pattern[end]) == kind:
            end += 1
        if kind == "skip":
            regex_src.append(_SEG)
        else:
            name = f"g{len(parts)}"
            regex_src.append(f"(?P<{name}>{_SEG})")
            parts.append((name, kind, pending_literal))
        pending_literal = ""
        index = end
    prefix = r"(?<![A-Za-z0-9_])" if first_is_segment or pattern[:1] == "-" else ""
    suffix = r"(?![A-Za-z0-9_])" if last_is_segment else ""
    # Ketten mit "-" (A-B-C-D) nicht an beliebiger Stelle anschneiden
    if first_is_segment and "-" in pattern:
        prefix += r"(?<![A-Za-z0-9_]-)"
    if re.search(r"-[xXyY]+$", pattern):
        suffix += r"(?!-[A-Za-z0-9_])"
    compiled = _Compiled(re.compile(prefix + "".join(regex_src) + suffix, re.IGNORECASE), parts)
    _compile_cache[pattern] = compiled
    return compiled


def _field_regex(entry: str) -> re.Pattern:
    """E/J/H -> "=E05"; Eintrag mit Ziffern (E00) -> genau dieses Feld "=E00"."""
    token = re.escape(entry.strip())
    body = token if re.search(r"\d", entry) else rf"{token}\d+"
    return re.compile(rf"=({body})(?![A-Za-z0-9_])", re.IGNORECASE)


class CabinetDetector:
    @staticmethod
    def extract(text: str, formats: list[CabinetFormat]) -> list[str]:
        """Schränke eines Textes (Großschreibung, ohne Duplikate, in Fundreihenfolge)."""
        found: dict[str, None] = {}
        for fmt in formats:
            if not fmt.enabled or not fmt.is_valid():
                continue
            compiled = _compile(fmt.pattern)
            for match in compiled.regex.finditer(text):
                out = ""
                for position, (name, kind, separator) in enumerate(compiled.parts):
                    if kind == "show" and not fmt.with_field:
                        continue
                    value = match.group(name)
                    out += (separator if out else "") + value
                if out:
                    found[out.upper()] = None
        return list(found)

    @staticmethod
    def extract_fields(texts: list[str], entries: tuple[str, ...]) -> dict[str, str]:
        """Felder je Eintrag (E, J, H oder eigene wie K / E00); mehrere Werte mit "/" verbunden."""
        result: dict[str, str] = {}
        for entry in entries:
            regex = _field_regex(entry)
            values: dict[str, None] = {}
            for text in texts:
                for m in regex.finditer(text):
                    values[m.group(1).upper()] = None
            result[entry] = "/".join(values)
        return result

    def detect(
        self,
        dataframe: pd.DataFrame,
        search_columns: list[str],
        formats: list[CabinetFormat],
    ) -> dict[str, list[int]]:
        """Ordnet jedem erkannten Schrank die Zeilenindizes zu (natürlich sortiert nach Name)."""
        usable = [f for f in formats if f.enabled and f.is_valid()]
        columns = [c for c in search_columns if c in dataframe.columns]
        if not columns or not usable:
            return {}
        by_cabinet: dict[str, list[int]] = {}
        stringified = {c: dataframe[c].map(stringify_cell) for c in columns}
        for idx in dataframe.index:
            row_cabinets: dict[str, None] = {}
            for column in columns:
                for cabinet in self.extract(stringified[column].at[idx], usable):
                    row_cabinets[cabinet] = None
            for cabinet in row_cabinets:
                by_cabinet.setdefault(cabinet, []).append(int(idx))
        return {name: by_cabinet[name] for name in sorted(by_cabinet, key=_natural_key)}

    def fields_for_rows(
        self,
        dataframe: pd.DataFrame,
        search_columns: list[str],
        entries: tuple[str, ...],
    ) -> dict[int, dict[str, str]]:
        """Je Zeile die Felder aus den Suchspalten, z. B. {3: {"E": "E05"}}."""
        columns = [c for c in search_columns if c in dataframe.columns]
        result: dict[int, dict[str, str]] = {}
        for idx, row in dataframe[columns].iterrows():
            result[idx] = self.extract_fields([stringify_cell(v) for v in row], entries)
        return result
