"""Übersetzer: Werte aus einer zweiten Tabelle (Quelle) anhand einer Schlüsselspalte (z. B. W-Nummer) in die Liste
(Ziel) eintragen. Nur die zugeordneten Spalten werden angefasst, alles andere bleibt unverändert."""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Literal

PREVIEW_LIMIT = 150


class TranslateError(ValueError):
    """Ungültige Konfiguration (wird als 422 gemeldet)."""


@dataclass
class Mapping:
    source: str
    target: str
    mode: Literal["empty", "overwrite"] = "overwrite"


@dataclass
class Options:
    key_a: str
    key_b: str
    ignore_case: bool = True
    ignore_separators: bool = False  # Leerzeichen, Bindestrich, Unterstrich, Punkt, Slash
    duplicates: Literal["first", "last", "skip"] = "first"
    mappings: list[Mapping] = field(default_factory=list)


def is_empty(value: Any) -> bool:
    return value is None or (isinstance(value, str) and not value.strip())


def normalize(value: Any, options: Options) -> str | None:
    if is_empty(value):
        return None
    text = str(value).strip()
    if options.ignore_case:
        text = text.casefold()
    if options.ignore_separators:
        text = re.sub(r"[\s\-_./]+", "", text)
    return text or None


def validate(options: Options, columns_a: list[str], columns_b: list[str]) -> None:
    if options.key_a not in columns_a:
        raise TranslateError(f"Schlüsselspalte „{options.key_a}“ gibt es in der Liste nicht.")
    if options.key_b not in columns_b:
        raise TranslateError(f"Schlüsselspalte „{options.key_b}“ gibt es in der Quelle nicht.")
    if not options.mappings:
        raise TranslateError("Bitte mindestens eine Spalte zuordnen.")
    seen: set[str] = set()
    for m in options.mappings:
        if m.source not in columns_b:
            raise TranslateError(f"Quellspalte „{m.source}“ gibt es nicht.")
        target = m.target.strip()
        if not target:
            raise TranslateError("Zielspalte fehlt.")
        if target == options.key_a:
            raise TranslateError("Die Schlüsselspalte darf nicht überschrieben werden.")
        if target in seen:
            raise TranslateError(f"Zielspalte „{target}“ ist mehrfach zugeordnet.")
        seen.add(target)


def build_index(rows_b: list[dict[str, Any]], options: Options) -> tuple[dict[str, list[dict[str, Any]]], int]:
    """Schlüssel -> Quellzeilen; zweiter Wert: Anzahl Schlüssel, die in der Quelle mehrfach vorkommen."""
    index: dict[str, list[dict[str, Any]]] = {}
    for row in rows_b:
        key = normalize(row.get(options.key_b), options)
        if key is not None:
            index.setdefault(key, []).append(row)
    return index, sum(1 for rows in index.values() if len(rows) > 1)


def pick(candidates: list[dict[str, Any]], policy: str) -> dict[str, Any] | None:
    if not candidates:
        return None
    if len(candidates) > 1 and policy == "skip":
        return None
    return candidates[-1] if policy == "last" else candidates[0]


@dataclass
class Plan:
    stats: dict[str, int]
    changes: dict[int, dict[str, Any]]  # Zeilen-ID -> {Zielspalte: neuer Wert}
    new_columns: list[str]
    sample: list[dict[str, Any]]
    unmatched_keys: list[str]


def make_plan(
    rows_a: list[tuple[int, dict[str, Any]]], columns_a: list[str], rows_b: list[dict[str, Any]],
    options: Options,
) -> Plan:
    index, duplicate_keys = build_index(rows_b, options)
    new_columns = [m.target.strip() for m in options.mappings if m.target.strip() not in columns_a]
    stats = {"rows": len(rows_a), "matched": 0, "unmatched": 0, "empty_key": 0, "ambiguous": 0,
             "changed_rows": 0, "changed_cells": 0, "duplicate_keys": duplicate_keys, "source_rows": len(rows_b)}
    changes: dict[int, dict[str, Any]] = {}
    sample: list[dict[str, Any]] = []
    unmatched: list[str] = []

    for position, (row_id, data) in enumerate(rows_a, start=1):
        raw_key = data.get(options.key_a)
        key = normalize(raw_key, options)
        status = "match"
        source: dict[str, Any] | None = None
        if key is None:
            status = "empty_key"
            stats["empty_key"] += 1
        else:
            candidates = index.get(key, [])
            source = pick(candidates, options.duplicates)
            if not candidates:
                status = "none"
                stats["unmatched"] += 1
                if len(unmatched) < 50:
                    unmatched.append(str(raw_key))
            elif source is None:
                status = "ambiguous"
                stats["ambiguous"] += 1
            else:
                stats["matched"] += 1

        patch: dict[str, Any] = {}
        cells: list[dict[str, Any]] = []
        if source is not None:
            for m in options.mappings:
                target = m.target.strip()
                new = source.get(m.source)
                old = data.get(target)
                skip = is_empty(new) or (m.mode == "empty" and not is_empty(old))
                changed = not skip and new != old
                if changed:
                    patch[target] = new
                cells.append({"target": target, "old": old, "new": new if not skip else None, "changed": changed})
        else:
            cells = [{"target": m.target.strip(), "old": data.get(m.target.strip()), "new": None, "changed": False}
                     for m in options.mappings]
        if patch:
            changes[row_id] = patch
            stats["changed_rows"] += 1
            stats["changed_cells"] += len(patch)
        if len(sample) < PREVIEW_LIMIT or patch:
            if len(sample) < PREVIEW_LIMIT * 4:
                sample.append({"row": position, "key": raw_key, "status": status, "cells": cells})
    return Plan(stats, changes, new_columns, sample, unmatched)


def apply_to_rows(
    rows_a: list[tuple[int, dict[str, Any]]], columns_a: list[str], plan: Plan,
) -> tuple[list[str], list[dict[str, Any]]]:
    """Liste mit angewandten Änderungen (für den Excel-Download, ohne die gespeicherte Liste zu ändern)."""
    columns = [*columns_a, *plan.new_columns]
    out = [{**data, **plan.changes.get(row_id, {})} for row_id, data in rows_a]
    return columns, out
