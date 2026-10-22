"""Die Werkzeuge der Desktop-App (Einzelsuche, Stapelsuche, Farbmarkierung, KMK, Schrank-Erkennung)
auf Basis der gemeinsamen core/-Logik. Eingabe: DataFrame (Index = Row.id) + Konfiguration im Vorlagenformat."""
from __future__ import annotations

import tempfile
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path
from typing import Any
from zipfile import ZIP_DEFLATED, ZipFile

import pandas as pd

from core.cabinet.cabinet_detector import CabinetDetector, formats_from_dicts
from core.color.color_manager import ColorManager
from core.export.export_payload_builder import ExportPayloadBuilder
from core.export.filename_builder import FilenameBuilder
from core.export.highlight_payload_builder import HighlightPayloadBuilder
from core.export.pdf_exporter import PdfExporter
from core.export.xlsx_exporter import XlsxExporter
from core.kmk.kmk_control_builder import KmkControlBuilder
from core.kmk.kmk_grid_xlsx import KmkGridXlsx
from core.kmk.kmk_label_builder import KmkLabelBuilder
from core.kmk.kmk_pdf_generator import KmkPdfGenerator
from core.models.batch_search import BatchSearchTerm
from core.models.color_models import ColorColumn, ColorSearchTerm
from core.models.column_config import ColumnConfig
from core.models.display_config import DisplayConfig
from core.models.export_header_config import build_export_header
from core.models.export_payload import ExportPayload
from core.models.global_fields import GlobalSettings
from core.models.kmk_models import KmkConfig
from core.models.search_options import SearchOptions
from core.models.separator_config import SeparatorConfig
from core.models.sort_config import SortConfig
from core.search.search_engine import SearchEngine

TOOLS = ("search", "batch", "highlight", "kmk", "cabinet")
PREVIEW_ROWS = 2000
CABINET_COLUMN_NAME = "Schrank"
DEFAULT_RESULT_SEPARATOR = "*"


class ToolError(ValueError):
    """Fehler in der Konfiguration (wird als 422 gemeldet)."""


@dataclass
class OutputFile:
    name: str
    content: bytes
    media_type: str


XLSX_TYPE = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
PDF_TYPE = "application/pdf"


# ---- Konfiguration ----

def make_frame(columns: list[str], rows: list[tuple[int, dict[str, Any]]]) -> pd.DataFrame:
    # dtype=object, sonst werden ganze Zahlen mit Lücken zu Kommazahlen (12 -> 12.0)
    frame = pd.DataFrame([{c: r.get(c) for c in columns} for _, r in rows], columns=columns, dtype=object,
                         index=pd.Index([rid for rid, _ in rows], dtype="int64"))
    return frame.where(frame.notna(), None)


def column_configs(config: dict[str, Any], frame_columns: list[str]) -> list[ColumnConfig]:
    """Spaltenkonfiguration aus der Vorlage; ohne Angabe sind alle Spalten Such- und Ausgabespalten."""
    given = {c["name"]: ColumnConfig.from_dict(c) for c in config.get("columns", []) if c.get("name") in frame_columns}
    if not given:
        return [ColumnConfig(name=n, search_enabled=True, output_enabled=True, output_order=i)
                for i, n in enumerate(frame_columns)]
    out = []
    for position, name in enumerate(frame_columns):
        out.append(given.get(name) or ColumnConfig(name=name, output_order=len(given) + position))
    return out


def _terms(config: dict[str, Any]) -> list[BatchSearchTerm]:
    items = config.get("batch_search_terms") or []
    if len(items) > 500:
        raise ToolError("Zu viele Suchbegriffe (max. 500).")
    return [BatchSearchTerm(term=str(t.get("term", "")), enabled=bool(t.get("enabled", True))) for t in items]


def _sections(config: dict[str, Any]) -> tuple[SortConfig, SeparatorConfig, DisplayConfig]:
    from core.models.template import Template  # Parser der Desktop-Vorlage wiederverwenden
    template = Template.from_dict({"name": "x", **{k: config.get(k) for k in ("sort", "separator", "display") if config.get(k)}})
    return template.sort, template.separator, template.display


def _header(globals_in: dict[str, Any] | None, result_name: str):
    return build_export_header(GlobalSettings.from_dict(globals_in), result_name)


def _stem(settings: GlobalSettings, original: str, term: str | None = None) -> str:
    company = settings.company.value if settings.company.enabled else None
    date = settings.date.value if settings.date.enabled else None
    if term:
        return FilenameBuilder.build_batch(company, date, term, original)
    return FilenameBuilder.build_single(company, date, original)


# ---- Payloads ----

def payload_json(payload: ExportPayload, limit: int = PREVIEW_ROWS) -> dict[str, Any]:
    return {
        "columns": [{"name": c.name, "width": c.width_px} for c in payload.columns],
        "rows": [{"values": r.values, "separator": r.is_separator, "color": r.row_color, "cells": r.cell_colors}
                 for r in payload.rows[:limit]],
        "total": sum(1 for r in payload.rows if not r.is_separator),
        "truncated": len(payload.rows) > limit,
        "header": {"left": payload.header.left, "center": payload.header.center, "right": payload.header.right},
        "landscape": payload.landscape,
    }


def search_payload(frame: pd.DataFrame, config: dict[str, Any], globals_in: dict | None, original: str,
                   term: str = "", min_chars: int = 3) -> ExportPayload:
    columns = column_configs(config, list(frame.columns))
    search_cols = [c.name for c in columns if c.search_enabled]
    options = SearchOptions(search_columns=search_cols, term=term, case_insensitive=True, min_chars=min_chars)
    hits = SearchEngine().search(frame, options).matched_indices
    sort, separator, display = _sections(config)
    settings = GlobalSettings.from_dict(globals_in)
    return ExportPayloadBuilder().build(frame, hits, columns, sort, separator, display,
                                        _header(globals_in, term or original), _stem(settings, original), )


def batch_payload(frame: pd.DataFrame, config: dict[str, Any], globals_in: dict | None, original: str,
                  term: str) -> ExportPayload:
    columns = column_configs(config, list(frame.columns))
    search_cols = [c.name for c in columns if c.search_enabled]
    if not search_cols:
        raise ToolError("Keine Suchspalte gewählt.")
    matched, values = SearchEngine().find_matches_with_actual_values(frame, search_cols, term, True)
    options = config.get("batch") or {}
    if options.get("result_column_enabled"):
        name = str(options.get("result_column_name") or "Ergebnis")
        separator_text = str(options.get("separator") or DEFAULT_RESULT_SEPARATOR)
        matched = matched.copy()
        matched[name] = [separator_text.join(values.get(i, [])) for i in matched.index]
        if all(c.name != name for c in columns):
            columns.append(ColumnConfig(name=name, output_enabled=True,
                                        output_order=max((c.output_order for c in columns), default=-1) + 1, width_px=140))
    sort, separator, display = _sections(config)
    settings = GlobalSettings.from_dict(globals_in)
    return ExportPayloadBuilder().build(matched, None, columns, sort, separator, display,
                                        _header(globals_in, term), _stem(settings, original, term))


def highlight_payload(frame: pd.DataFrame, config: dict[str, Any], globals_in: dict | None, original: str) -> ExportPayload:
    columns = column_configs(config, list(frame.columns))
    manager = ColorManager.from_list(config.get("colors") or [], config.get("color_columns") or [])
    cc_ids: dict[str, int] = {}
    next_order = max((c.output_order for c in columns if c.output_enabled), default=-1) + 1
    for i, raw in enumerate(config.get("color_columns") or []):
        cc = ColorColumn.from_dict(raw)
        key = f"\x00cc{cc.id}"
        columns.append(ColumnConfig(name=key, display_name=cc.name, output_enabled=bool(raw.get("output_enabled", True)),
                                    output_order=int(raw.get("output_order", next_order + i)), width_px=cc.width_px))
        cc_ids[key] = cc.id
    terms = [ColorSearchTerm.from_dict(t) for t in config.get("color_search_terms") or []]
    sort, separator, display = _sections(config)
    settings = GlobalSettings.from_dict(globals_in)
    payload = HighlightPayloadBuilder().build(
        frame, columns, terms, manager, sort, separator, display, _header(globals_in, original),
        _stem(settings, original), min_matches=int(config.get("color_min_matches", 2)), cc_col_ids=cc_ids)
    if payload is None:
        raise ToolError("Keine Ausgabespalte gewählt.")
    return payload


def cabinet_setup(frame: pd.DataFrame, config: dict[str, Any]):
    cab = config.get("cabinet_config") or {}
    columns = column_configs(config, list(frame.columns))
    search_cols = [c.name for c in columns if c.search_enabled]
    detected = CabinetDetector().detect(frame, search_cols, formats_from_dicts(cab.get("formats")))
    return cab, columns, search_cols, detected


def cabinet_fields(cab: dict[str, Any]) -> tuple[str, ...]:
    entries = [letter for letter, on in (cab.get("fields") or {}).items() if on]
    for raw in str(cab.get("custom_fields", "")).split(","):
        entry = raw.strip().upper()
        if entry and entry.isalnum() and entry not in entries:
            entries.append(entry)
    return tuple(entries)


def cabinet_payload(frame: pd.DataFrame, config: dict[str, Any], globals_in: dict | None, original: str,
                    cabinet: str, indices: list[int]) -> ExportPayload:
    cab, columns, search_cols, _ = cabinet_setup(frame, config)
    part = frame.loc[indices].copy()
    if cab.get("cabinet_column", True) and CABINET_COLUMN_NAME not in part.columns:
        part[CABINET_COLUMN_NAME] = cabinet
        columns.append(ColumnConfig(name=CABINET_COLUMN_NAME, output_enabled=True, width_px=80,
                                    output_order=max((c.output_order for c in columns), default=-1) + 1))
    entries = cabinet_fields(cab)
    if entries:
        values = CabinetDetector().fields_for_rows(part, search_cols, entries)
        for entry in entries:
            name = f"{entry}-Feld"
            if name in part.columns:
                continue
            part[name] = [values[i][entry] for i in part.index]
            columns.append(ColumnConfig(name=name, output_enabled=True, width_px=70,
                                        output_order=max((c.output_order for c in columns), default=-1) + 1))
    sort, separator, display = _sections(config)
    settings = GlobalSettings.from_dict(globals_in)
    return ExportPayloadBuilder().build(part, None, columns, sort, separator, display,
                                        _header(globals_in, f"Schrank {cabinet}"), _stem(settings, original, cabinet))


# ---- KMK ----

def kmk_config(config: dict[str, Any], columns: list[ColumnConfig]) -> KmkConfig:
    cfg = KmkConfig.from_dict(config.get("kmk_config") or {})
    if not cfg.label_column_names:
        content = cfg.label_content or {}
        order = content.get("order") or [c.name for c in columns if c.output_enabled]
        enabled = content.get("enabled") or {}
        cfg.label_column_names = [n for n in order if enabled.get(n, True)]
    return cfg


def kmk_groups(frame: pd.DataFrame, config: dict[str, Any]):
    columns = column_configs(config, list(frame.columns))
    cfg = kmk_config(config, columns)
    groups = KmkLabelBuilder().build_groups(
        frame, [c.name for c in columns if c.search_enabled], _terms(config), cfg.label_column_names)
    if not cfg.include_reste:
        groups = KmkLabelBuilder.drop_reste(groups)
    return groups, cfg, columns


def kmk_preview(frame: pd.DataFrame, config: dict[str, Any]) -> dict[str, Any]:
    groups, cfg, _ = kmk_groups(frame, config)
    with tempfile.TemporaryDirectory() as tmp:
        warnings = KmkPdfGenerator().generate(groups, cfg, Path(tmp) / "preview.pdf") if groups else []
    return {
        "groups": [{"title": g.title, "count": len(g.labels),
                    "labels": [{"lines": lb.lines, "row_id": lb.source_index} for lb in g.labels[:300]]} for g in groups],
        "labels": sum(len(g.labels) for g in groups),
        "row_ids": sorted({lb.source_index for g in groups for lb in g.labels if lb.source_index is not None}),
        "warnings": warnings,
    }


def kmk_files(frame: pd.DataFrame, config: dict[str, Any], globals_in: dict | None, original: str,
              formats: list[str]) -> tuple[list[OutputFile], list[int], list[str]]:
    groups, cfg, columns = kmk_groups(frame, config)
    if not groups:
        raise ToolError("Keine Treffer zum Exportieren.")
    settings = GlobalSettings.from_dict(globals_in)
    stem = _stem(settings, original) + "_KMK"
    files: list[OutputFile] = []
    warnings: list[str] = []
    with tempfile.TemporaryDirectory() as tmp:
        if "pdf" in formats:
            path = Path(tmp) / f"{stem}.pdf"
            warnings = KmkPdfGenerator().generate(groups, cfg, path)
            files.append(OutputFile(path.name, path.read_bytes(), PDF_TYPE))
        if "xlsx" in formats:
            path = Path(tmp) / f"{stem}.xlsx"
            payload = KmkControlBuilder().build(frame, groups, columns, _header(globals_in, original), stem, cfg.header_mode)
            KmkGridXlsx().write(groups, cfg, path, list_payload=payload)
            files.append(OutputFile(path.name, path.read_bytes(), XLSX_TYPE))
    row_ids = sorted({lb.source_index for g in groups for lb in g.labels if lb.source_index is not None})
    return files, row_ids, warnings


# ---- Dateien ----

def render(payload: ExportPayload, formats: list[str], stem: str | None = None) -> list[OutputFile]:
    stem = stem or payload.filename_stem
    files: list[OutputFile] = []
    with tempfile.TemporaryDirectory() as tmp:
        if "xlsx" in formats:
            path = Path(tmp) / f"{stem}.xlsx"
            XlsxExporter().export(payload, path)
            files.append(OutputFile(path.name, path.read_bytes(), XLSX_TYPE))
        if "pdf" in formats:
            path = Path(tmp) / f"{stem}.pdf"
            PdfExporter().export(payload, path)
            files.append(OutputFile(path.name, path.read_bytes(), PDF_TYPE))
    return files


def combined(sheets: list[tuple[str, ExportPayload]], formats: list[str], stem: str) -> list[OutputFile]:
    """Sammeldatei: Excel mit einem Blatt je Eintrag, PDF mit neuer Seite je Eintrag."""
    files: list[OutputFile] = []
    with tempfile.TemporaryDirectory() as tmp:
        if "xlsx" in formats:
            path = Path(tmp) / f"{stem}.xlsx"
            XlsxExporter().export_many(sheets, path)
            files.append(OutputFile(path.name, path.read_bytes(), XLSX_TYPE))
        if "pdf" in formats:
            path = Path(tmp) / f"{stem}.pdf"
            PdfExporter().export_many([p for _, p in sheets], path)
            files.append(OutputFile(path.name, path.read_bytes(), PDF_TYPE))
    return files


def zip_files(files: list[OutputFile]) -> bytes:
    buffer = BytesIO()
    with ZipFile(buffer, "w", ZIP_DEFLATED) as archive:
        used: set[str] = set()
        for f in files:
            name, n = f.name, 1
            while name in used:
                n += 1
                name = f"{Path(f.name).stem}_{n}{Path(f.name).suffix}"
            used.add(name)
            archive.writestr(name, f.content)
    return buffer.getvalue()
