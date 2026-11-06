"""Excel-Werkzeuge: zwei hochgeladene Dateien abgleichen (ohne Projekt, nichts wird auf dem Server gespeichert)."""
from __future__ import annotations

from typing import Any, Literal
from urllib.parse import quote

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from fastapi.responses import Response
from pydantic import BaseModel, Field, ValidationError

from wtserver import excel_transfer as xt
from wtserver.models import User
from wtserver.security import current_user

router = APIRouter(prefix="/api/exceltools", tags=["exceltools"])

MAX_FILE = 50 * 1024 * 1024
XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


class Pair(BaseModel):
    source: str = Field(min_length=1)
    target: str = ""  # leer = gleicher Name wie in der Quelle


class TransferCfg(BaseModel):
    source_sheet: str = ""
    source_header: int = Field(default=1, ge=1, le=1000)
    source_key: str = Field(min_length=1)
    target_sheet: str = ""
    target_header: int = Field(default=1, ge=1, le=1000)
    target_key: str = Field(min_length=1)
    pairs: list[Pair] = Field(default_factory=list)
    overwrite: Literal["always", "empty"] = "always"
    skip_empty: bool = True  # leere Werte der Quelle überschreiben nichts


class FillCfg(BaseModel):
    source_sheet: str = ""
    source_header: int = Field(default=1, ge=1, le=1000)
    source_key: str = Field(min_length=1)
    source_value: str = Field(min_length=1)
    target_header: int = Field(default=1, ge=1, le=1000)
    target_column: str = Field(min_length=1)  # Spaltenname aus der Kopfzeile oder Buchstabe
    target_key_column: str = ""  # leer = Schlüssel in allen Zellen suchen
    target_sheets: list[str] = Field(default_factory=list)  # leer = alle Blätter
    overwrite: Literal["always", "empty"] = "always"
    skip_empty: bool = True


def _read(upload: UploadFile) -> bytes:
    data = upload.file.read(MAX_FILE + 1)
    if len(data) > MAX_FILE:
        raise HTTPException(status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, "Datei ist größer als 50 MB.")
    if not data:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Leere Datei.")
    return data


def _config(model: type[BaseModel], text: str) -> dict[str, Any]:
    try:
        return model.model_validate_json(text).model_dump()
    except ValidationError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Ungültige Einstellungen: bitte alle Spalten wählen.") from exc


def _run(func, source: UploadFile, target: UploadFile, cfg: dict[str, Any], apply: bool) -> Response | dict[str, Any]:
    try:
        summary, content = func(_read(source), _read(target), cfg, apply)
    except xt.ExcelToolError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from exc
    if content is None:
        return summary
    stem = (target.filename or "Ziel").rsplit(".", 1)[0]
    return Response(content, media_type=XLSX,
                    headers={"Content-Disposition": f"attachment; filename*=UTF-8''{quote(stem + ' (aktualisiert).xlsx')}"})


@router.post("/inspect")
def inspect_file(file: UploadFile = File(...), header_row: int = Form(1), _user: User = Depends(current_user)) -> dict:
    """Blätter und Spaltennamen (aus der Kopfzeile) einer hochgeladenen Datei."""
    try:
        return {"sheets": xt.inspect(_read(file), max(1, header_row))}
    except xt.ExcelToolError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from exc


@router.post("/transfer")
def transfer(source: UploadFile = File(...), target: UploadFile = File(...), config: str = Form(...), apply: bool = Form(False),
             _user: User = Depends(current_user)):
    """Werkzeug 1: Spalten von der Quelle in die Zieldatei übertragen (Zeilen über eine Schlüsselspalte).
    Ohne `apply` nur Vorschau (JSON), sonst die geänderte Zieldatei."""
    return _run(xt.transfer, source, target, _config(TransferCfg, config), apply)


@router.post("/fill")
def fill(source: UploadFile = File(...), target: UploadFile = File(...), config: str = Form(...), apply: bool = Form(False),
         _user: User = Depends(current_user)):
    """Werkzeug 2: Wert zum Schlüssel überall in der Zieldatei eintragen. Ohne `apply` nur Vorschau."""
    return _run(xt.fill_by_key, source, target, _config(FillCfg, config), apply)
