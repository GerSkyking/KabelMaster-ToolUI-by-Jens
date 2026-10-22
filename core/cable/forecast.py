"""Längen-Prognose für noch offene Kabel.

Grundannahme: Kabel mit demselben Querschnitt und denselben Zielen (Ziel 1 / Ziel 2) sind gleich lang.
Je Gruppe wird der Durchschnitt der ersten gezogenen Kabel (Standard: 1-3) als Prognose für die noch offenen
Kabel dieser Gruppe verwendet. Gibt es für ein Kabel keine solche Gruppe, wird ersatzweise das Verhältnis
gezogene / veranschlagte Länge der ersten gezogenen Kabel desselben Querschnitts auf die Soll-Länge angewendet;
ohne jede Vergleichsbasis bleibt die Soll-Länge.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import pandas as pd

from core.cable.cable_analysis import NO_CROSS_SECTION_LABEL, is_ignored, parse_number
from core.cable.report import parse_date

SAMPLE_SIZE = 3

BASIS_DONE = "done"
BASIS_ROUTE = "route"
BASIS_RATIO = "ratio"
BASIS_SOLL = "soll"


@dataclass
class RowForecast:
    length: float | None
    basis: str


@dataclass
class SectionForecast:
    label: str
    total: int = 0
    done: int = 0
    planned_m: float = 0.0  # veranschlagte Meter aller gezählten Kabel
    done_m: float = 0.0  # tatsächlich gezogene Meter
    predicted_open_m: float = 0.0  # prognostizierte Meter der offenen Kabel
    basis_counts: dict[str, int] = field(default_factory=lambda: {BASIS_ROUTE: 0, BASIS_RATIO: 0, BASIS_SOLL: 0})

    @property
    def open(self) -> int:
        return self.total - self.done

    @property
    def forecast_m(self) -> float:
        return self.done_m + self.predicted_open_m

    @property
    def delta_m(self) -> float:
        return self.forecast_m - self.planned_m

    @property
    def delta_percent(self) -> float:
        return 100.0 * self.delta_m / self.planned_m if self.planned_m else 0.0


@dataclass
class ForecastResult:
    rows: dict[Any, RowForecast] = field(default_factory=dict)  # Schlüssel = DataFrame-Index
    sections: list[SectionForecast] = field(default_factory=list)
    total: SectionForecast = field(default_factory=lambda: SectionForecast("Gesamt"))


def _text(value: object) -> str:
    return "" if value is None or (isinstance(value, float) and pd.isna(value)) else str(value).strip()


def _route(first: object, second: object) -> tuple[str, str] | None:
    a, b = _text(first).lower(), _text(second).lower()
    if not a and not b:
        return None
    return (a, b) if a <= b else (b, a)  # A->B und B->A sind dieselbe Strecke


def _section_sort_key(label: str) -> tuple[float, str]:
    number = parse_number(label)
    return (number if number is not None else float("inf"), label)


def forecast(
    dataframe: pd.DataFrame,
    mapping: dict[str, str | None],
    ignore_short: bool = False,
    min_length: float = 0.0,
    sample_size: int = SAMPLE_SIZE,
) -> ForecastResult:
    col = lambda key: mapping.get(key) or ""  # noqa: E731
    has = lambda key: bool(mapping.get(key)) and mapping[key] in dataframe.columns  # noqa: E731

    entries: list[dict[str, Any]] = []
    for position, (index, row) in enumerate(dataframe.iterrows()):
        target = row[col("target_length")] if has("target_length") else None
        if is_ignored(target, ignore_short, min_length):
            continue
        label = _text(row[col("cross_section")]) if has("cross_section") else ""
        pulled = (parse_number(row[col("pulled_length")]) if has("pulled_length") else None) or 0.0
        when = parse_date(row[col("date")]) if has("date") else None
        entries.append({
            "index": index, "order": position, "label": label or NO_CROSS_SECTION_LABEL,
            "soll": parse_number(target) or 0.0, "pulled": pulled if pulled > 0 else None, "when": when,
            "route": _route(row[col("target1")] if has("target1") else None,
                            row[col("target2")] if has("target2") else None),
        })

    # Referenzen: die ersten gezogenen Kabel je Gruppe (nach Datum, dann Listenreihenfolge)
    done = sorted((e for e in entries if e["pulled"]), key=lambda e: (e["when"] is None, e["when"], e["order"]))
    by_route: dict[tuple, list[float]] = {}
    by_section: dict[str, list[float]] = {}
    for e in done:
        if e["route"] is not None and len(refs := by_route.setdefault((e["label"], e["route"]), [])) < sample_size:
            refs.append(e["pulled"])
        if e["soll"] > 0 and len(ratios := by_section.setdefault(e["label"], [])) < sample_size:
            ratios.append(e["pulled"] / e["soll"])

    result = ForecastResult()
    sections: dict[str, SectionForecast] = {}
    for e in entries:
        section = sections.setdefault(e["label"], SectionForecast(e["label"]))
        if e["pulled"]:
            guess, basis = e["pulled"], BASIS_DONE
        elif e["route"] is not None and by_route.get((e["label"], e["route"])):
            refs = by_route[(e["label"], e["route"])]
            guess, basis = round(sum(refs) / len(refs), 2), BASIS_ROUTE
        elif by_section.get(e["label"]) and e["soll"] > 0:
            ratios = by_section[e["label"]]
            guess, basis = round(e["soll"] * sum(ratios) / len(ratios), 2), BASIS_RATIO
        else:
            guess, basis = (e["soll"] or None), BASIS_SOLL
        result.rows[e["index"]] = RowForecast(guess, basis)
        for bucket in (section, result.total):
            bucket.total += 1
            bucket.planned_m += e["soll"]
            if basis == BASIS_DONE:
                bucket.done += 1
                bucket.done_m += e["pulled"]
            else:
                bucket.predicted_open_m += guess or 0.0
                bucket.basis_counts[basis] += 1
    result.sections = sorted(sections.values(), key=lambda s: _section_sort_key(s.label))
    return result
