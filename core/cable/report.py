"""Tagesbericht als Text: pro Tag gezogene Kabel und Meter, aufgeschlüsselt nach Querschnitt."""
from __future__ import annotations

import re
from collections import defaultdict
from datetime import date, datetime
from typing import Any

import pandas as pd

from core.cable.cable_analysis import NO_CROSS_SECTION_LABEL, format_number, parse_number

DATE_FORMAT = "%d.%m.%y"
_DMY = re.compile(r"^\s*(\d{1,2})\.(\d{1,2})\.(\d{2}|\d{4})\s*$")
_ISO = re.compile(r"^\s*(\d{4})-(\d{2})-(\d{2})")


def parse_date(value: object) -> date | None:
    """Liest TT.MM.JJ, TT.MM.JJJJ, JJJJ-MM-TT und Datumsobjekte; sonst None."""
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text = str(value)
    try:
        if m := _DMY.match(text):
            day, month, year = int(m[1]), int(m[2]), int(m[3])
            return date(2000 + year if year < 100 else year, month, day)
        if m := _ISO.match(text):
            return date(int(m[1]), int(m[2]), int(m[3]))
    except ValueError:
        return None
    return None


def collect_days(
    dataframe: pd.DataFrame, mapping: dict[str, Any], start: date | None = None, end: date | None = None
) -> tuple[dict[date | None, dict[str, list[float]]], int]:
    """{Tag: {Querschnitt: [Längen]}} für gezogene Kabel; Schlüssel None = ohne Datum. Zweiter Wert: Anzahl ignoriert."""
    pulled_col, date_col, section_col = mapping.get("pulled_length"), mapping.get("date"), mapping.get("cross_section")
    days: dict[date | None, dict[str, list[float]]] = defaultdict(lambda: defaultdict(list))
    skipped = 0
    for _, row in dataframe.iterrows():
        length = parse_number(row[pulled_col]) if pulled_col in dataframe.columns else None
        if not length or length <= 0:
            continue
        day = parse_date(row[date_col]) if date_col in dataframe.columns else None
        if day is not None and ((start and day < start) or (end and day > end)):
            skipped += 1
            continue
        if day is None and (start or end):
            skipped += 1
            continue
        raw = row[section_col] if section_col in dataframe.columns else None
        label = NO_CROSS_SECTION_LABEL if raw is None or (isinstance(raw, float) and pd.isna(raw)) or not str(raw).strip() else str(raw).strip()
        days[day][label].append(length)
    return days, skipped


def _line(count: int, meters: float) -> str:
    return f"{count} Kabel, {format_number(meters)} m"


def daily_report_text(
    dataframe: pd.DataFrame,
    mapping: dict[str, Any],
    title: str = "",
    start: date | None = None,
    end: date | None = None,
    generated: datetime | None = None,
) -> str:
    days, _ = collect_days(dataframe, mapping, start, end)
    now = generated or datetime.now()
    lines = ["UW Kabel-Master ToolUI by Jens - Tagesbericht Kabelzug"]
    if title:
        lines.append(title)
    if start or end:
        lines.append(f"Zeitraum: {start.strftime(DATE_FORMAT) if start else 'Anfang'} - {end.strftime(DATE_FORMAT) if end else 'heute'}")
    lines += [f"Erstellt: {now.strftime('%d.%m.%y %H:%M')}", ""]

    total_count, total_m = 0, 0.0
    per_section_total: dict[str, list[float]] = defaultdict(list)
    ordered = sorted((d for d in days if d is not None)) + ([None] if None in days else [])
    for day in ordered:
        sections = days[day]
        count = sum(len(v) for v in sections.values())
        meters = sum(sum(v) for v in sections.values())
        lines.append(f"== {day.strftime(DATE_FORMAT) if day else 'ohne Datum'} ==")
        lines.append(f"Gesamt: {_line(count, meters)}")
        for label in sorted(sections, key=lambda s: (parse_number(s) is None, parse_number(s) or 0, s)):
            lines.append(f"  {label}: {_line(len(sections[label]), sum(sections[label]))}")
            per_section_total[label].extend(sections[label])
        lines.append("")
        total_count += count
        total_m += meters
    if not ordered:
        lines += ["Keine gezogenen Kabel im Zeitraum.", ""]
    else:
        lines.append("== Summe ==")
        lines.append(f"Gesamt: {_line(total_count, total_m)}")
        for label in sorted(per_section_total, key=lambda s: (parse_number(s) is None, parse_number(s) or 0, s)):
            lines.append(f"  {label}: {_line(len(per_section_total[label]), sum(per_section_total[label]))}")
    return "\n".join(lines).rstrip() + "\n"
