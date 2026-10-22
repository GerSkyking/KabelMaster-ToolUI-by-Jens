"""Kabelzug-Logik: Länge aus Von/Bis (Meterzahlen) und Fortschrittsanalyse je Querschnitt.

Ein Kabel gilt als "gezogen", sobald in der Ergebnisspalte eine Länge > 0 steht
(diese wird aus |Bis - Von| berechnet). Kurze Enden unterhalb einer frei wählbaren
Soll-Länge können aus der Analyse ausgenommen werden.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

import pandas as pd

TOTAL_LABEL = "Gesamt"
NO_CROSS_SECTION_LABEL = "(ohne Querschnitt)"
_NUMBER_RE = re.compile(r"-?\d+(?:[.,]\d+)?")


@dataclass(frozen=True)
class CableColumns:
    """Spaltenzuordnung der Kabelliste."""

    cable_id: str
    cross_section: str
    target_length: str
    start: str
    end: str
    pulled_length: str
    date: str = ""


@dataclass
class GroupStats:
    label: str
    total: int = 0
    done: int = 0
    meters_total: float = 0.0
    meters_done: float = 0.0

    @property
    def open(self) -> int:
        return self.total - self.done

    @property
    def meters_open(self) -> float:
        return max(self.meters_total - self.meters_done, 0.0)

    @property
    def percent_count(self) -> float:
        return 100.0 * self.done / self.total if self.total else 0.0

    @property
    def percent_meters(self) -> float:
        return min(100.0 * self.meters_done / self.meters_total, 100.0) if self.meters_total else 0.0


@dataclass
class AnalysisResult:
    groups: list[GroupStats] = field(default_factory=list)
    total: GroupStats = field(default_factory=lambda: GroupStats(TOTAL_LABEL))
    ignored: int = 0


def parse_number(value: object) -> float | None:
    """Liest eine Zahl aus Zelleninhalt ("12,5", "12.5 m", 12) - None, wenn keine erkennbar ist."""
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return None if pd.isna(value) else float(value)
    match = _NUMBER_RE.search(str(value))
    return float(match.group().replace(",", ".")) if match else None


def compute_length(start: object, end: object) -> float | None:
    """Gezogene Länge aus den Meterzahlen auf dem Kabel; None, wenn eine der beiden fehlt."""
    a, b = parse_number(start), parse_number(end)
    if a is None or b is None:
        return None
    return round(abs(b - a), 2)


def format_number(value: float) -> str:
    return f"{value:.2f}".rstrip("0").rstrip(".").replace(".", ",")


def is_ignored(target_length: object, ignore_short: bool, min_length: float) -> bool:
    if not ignore_short:
        return False
    length = parse_number(target_length)
    return length is not None and length < min_length


def analyze(
    dataframe: pd.DataFrame, columns: CableColumns, ignore_short: bool = False, min_length: float = 0.0
) -> AnalysisResult:
    result = AnalysisResult()
    groups: dict[str, GroupStats] = {}
    for target, section, pulled in zip(
        dataframe[columns.target_length], dataframe[columns.cross_section], dataframe[columns.pulled_length]
    ):
        if is_ignored(target, ignore_short, min_length):
            result.ignored += 1
            continue
        label = "" if section is None or pd.isna(section) else str(section).strip()
        stats = groups.setdefault(label or NO_CROSS_SECTION_LABEL, GroupStats(label or NO_CROSS_SECTION_LABEL))
        meters = parse_number(target) or 0.0
        done = (parse_number(pulled) or 0.0) > 0
        for bucket in (stats, result.total):
            bucket.total += 1
            bucket.meters_total += meters
            if done:
                bucket.done += 1
                bucket.meters_done += meters
    result.groups = sorted(groups.values(), key=lambda g: _section_sort_key(g.label))
    return result


def _section_sort_key(label: str) -> tuple[float, str]:
    number = parse_number(label)
    return (number if number is not None else float("inf"), label)
