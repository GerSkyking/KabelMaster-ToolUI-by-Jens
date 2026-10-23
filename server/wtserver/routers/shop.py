"""Einkauf/Packliste: allgemeiner Artikelkatalog (mit Bild und Artikelnummer) und Bedarf je Projekt zum Abhaken.
Abgehakte Einträge bleiben als Archiv erhalten und lassen sich auswerten."""
from __future__ import annotations

import io
import secrets

from fastapi import APIRouter, Depends, File, HTTPException, Query, Request, UploadFile, status
from fastapi.responses import FileResponse, Response
from openpyxl import Workbook
from pydantic import BaseModel, Field
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from wtserver import audit
from wtserver.config import Settings, get_settings
from wtserver.db import get_db
from wtserver.models import CatalogItem, ShopRequest, User, utcnow
from wtserver.scope import (check_scope, day_end, day_start, member_project_ids, project_names, to_local, tzinfo,
                            valid_day)
from wtserver.security import current_user

router = APIRouter(prefix="/api/shop", tags=["shop"])

MAX_IMAGE = 3 * 1024 * 1024
IMAGE_MAGIC = ((b"\x89PNG\r\n\x1a\n", ".png"), (b"\xff\xd8\xff", ".jpg"), (b"GIF8", ".gif"))


class CatalogIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    article_no: str = Field(default="", max_length=100)
    category: str = Field(default="", max_length=100)
    unit: str = Field(default="Stk", max_length=30)
    note: str = Field(default="", max_length=500)


class CatalogPatch(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    article_no: str | None = Field(default=None, max_length=100)
    category: str | None = Field(default=None, max_length=100)
    unit: str | None = Field(default=None, max_length=30)
    note: str | None = Field(default=None, max_length=500)


class RequestIn(BaseModel):
    catalog_id: int | None = None
    title: str = Field(default="", max_length=200)  # bei Katalogartikel leer lassen
    article_no: str = Field(default="", max_length=100)
    unit: str = Field(default="", max_length=30)
    qty: float = Field(default=1, gt=0, le=1_000_000)
    kind: str = Field(default="bringen", pattern="^(bringen|pruefen)$")
    project_id: int | None = None
    due: str = ""
    note: str = Field(default="", max_length=500)


class RequestPatch(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=200)
    qty: float | None = Field(default=None, gt=0, le=1_000_000)
    kind: str | None = Field(default=None, pattern="^(bringen|pruefen)$")
    due: str | None = None
    note: str | None = Field(default=None, max_length=500)


class Flag(BaseModel):
    value: bool = True


def catalog_out(item: CatalogItem) -> dict:
    return {"id": item.id, "name": item.name, "article_no": item.article_no, "category": item.category,
            "unit": item.unit, "note": item.note, "created_by": item.created_by,
            "image_url": f"/api/shop/catalog/{item.id}/image?v={item.image}" if item.image else ""}


def status_of(req: ShopRequest) -> str:
    return "done" if req.done_at else "packed" if req.packed_at else "open"


def request_out(req: ShopRequest, names: dict[int, str], image: str = "") -> dict:
    return {"id": req.id, "project_id": req.project_id, "project": names.get(req.project_id, "") if req.project_id else "",
            "catalog_id": req.catalog_id, "title": req.title, "article_no": req.article_no, "unit": req.unit,
            "qty": req.qty, "kind": req.kind, "due": req.due, "note": req.note, "status": status_of(req),
            "requested_by": req.requested_by, "created_at": req.created_at,
            "packed_by": req.packed_by, "packed_at": req.packed_at, "done_by": req.done_by, "done_at": req.done_at,
            "image_url": image}


def _like(q: str) -> str:
    return f"%{q.strip().replace('%', '').replace('_', '')}%"


# ---- Katalog ----

@router.get("/catalog")
def list_catalog(q: str = "", category: str = "", user: User = Depends(current_user), db: Session = Depends(get_db)) -> list[dict]:
    stmt = select(CatalogItem).order_by(CatalogItem.name)
    if q.strip():
        pattern = _like(q)
        stmt = stmt.where(or_(CatalogItem.name.ilike(pattern), CatalogItem.article_no.ilike(pattern),
                              CatalogItem.category.ilike(pattern), CatalogItem.note.ilike(pattern)))
    if category:
        stmt = stmt.where(CatalogItem.category == category)
    return [catalog_out(i) for i in db.scalars(stmt.limit(1000))]


@router.get("/categories")
def categories(user: User = Depends(current_user), db: Session = Depends(get_db)) -> list[str]:
    return sorted({c for c in db.scalars(select(CatalogItem.category).distinct()) if c})


@router.post("/catalog", status_code=201)
def create_catalog(body: CatalogIn, request: Request, user: User = Depends(current_user), db: Session = Depends(get_db)) -> dict:
    item = CatalogItem(**{k: v.strip() for k, v in body.model_dump().items()}, created_by=user.username)
    db.add(item)
    db.flush()
    audit.record(db, request, "catalog_created", user, f"catalog:{item.id}", {"name": item.name})
    db.commit()
    return catalog_out(item)


def _item(db: Session, item_id: int) -> CatalogItem:
    item = db.get(CatalogItem, item_id)
    if item is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Artikel nicht gefunden.")
    return item


@router.patch("/catalog/{item_id}")
def patch_catalog(item_id: int, body: CatalogPatch, user: User = Depends(current_user), db: Session = Depends(get_db)) -> dict:
    item = _item(db, item_id)
    for key, value in body.model_dump(exclude_none=True).items():
        setattr(item, key, value.strip())
    db.commit()
    return catalog_out(item)


def _remove_image(settings: Settings, item: CatalogItem) -> None:
    if item.image:
        (settings.catalog_dir / item.image).unlink(missing_ok=True)
        item.image = ""


@router.delete("/catalog/{item_id}", status_code=204)
def delete_catalog(
    item_id: int, request: Request, user: User = Depends(current_user), db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> None:
    item = _item(db, item_id)
    _remove_image(settings, item)
    audit.record(db, request, "catalog_deleted", user, f"catalog:{item.id}", {"name": item.name})
    db.delete(item)
    db.commit()


@router.put("/catalog/{item_id}/image")
async def put_image(
    item_id: int, file: UploadFile = File(...), user: User = Depends(current_user),
    db: Session = Depends(get_db), settings: Settings = Depends(get_settings),
) -> dict:
    item = _item(db, item_id)
    data = await file.read(MAX_IMAGE + 1)
    if len(data) > MAX_IMAGE:
        raise HTTPException(status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, "Bild größer als 3 MB.")
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        ext = ".webp"
    else:  # nur Formate, die der Browser als Bild zeigt (kein SVG: könnte Skripte enthalten)
        ext = next((e for magic, e in IMAGE_MAGIC if data.startswith(magic)), "")
    if not ext:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Nur PNG, JPEG, GIF oder WebP erlaubt.")
    settings.catalog_dir.mkdir(parents=True, exist_ok=True)
    _remove_image(settings, item)
    item.image = f"{item.id}-{secrets.token_hex(4)}{ext}"
    (settings.catalog_dir / item.image).write_bytes(data)
    db.commit()
    return catalog_out(item)


@router.delete("/catalog/{item_id}/image", status_code=204)
def delete_image(item_id: int, user: User = Depends(current_user), db: Session = Depends(get_db),
                 settings: Settings = Depends(get_settings)) -> None:
    _remove_image(settings, _item(db, item_id))
    db.commit()


@router.get("/catalog/{item_id}/image")
def get_image(item_id: int, user: User = Depends(current_user), db: Session = Depends(get_db),
              settings: Settings = Depends(get_settings)) -> FileResponse:
    item = _item(db, item_id)
    path = settings.catalog_dir / item.image if item.image else None
    if path is None or not path.is_file():
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Kein Bild.")
    return FileResponse(path, headers={"Cache-Control": "private, max-age=86400"})


# ---- Bedarf ----

def _image_map(db: Session, ids: set[int | None]) -> dict[int, str]:
    wanted = [i for i in ids if i]
    if not wanted:
        return {}
    return {i.id: catalog_out(i)["image_url"] for i in db.scalars(select(CatalogItem).where(CatalogItem.id.in_(wanted))) if i.image}


def _filtered(db: Session, user: User, project_id: int | None, all_projects: bool, state: str, q: str,
              date_from: str, date_to: str) -> list[ShopRequest]:
    stmt = select(ShopRequest)
    if project_id is not None:
        check_scope(db, user, project_id)
        stmt = stmt.where(ShopRequest.project_id == project_id)
    elif all_projects:
        stmt = stmt.where(or_(ShopRequest.project_id.is_(None), ShopRequest.project_id.in_(member_project_ids(db, user))))
    else:
        stmt = stmt.where(ShopRequest.project_id.is_(None))
    if state == "open":
        stmt = stmt.where(ShopRequest.done_at.is_(None))
    elif state == "packed":
        stmt = stmt.where(ShopRequest.done_at.is_(None), ShopRequest.packed_at.is_not(None))
    elif state == "done":
        stmt = stmt.where(ShopRequest.done_at.is_not(None))
    if q.strip():
        pattern = _like(q)
        stmt = stmt.where(or_(ShopRequest.title.ilike(pattern), ShopRequest.article_no.ilike(pattern), ShopRequest.note.ilike(pattern)))
    date_col = ShopRequest.done_at if state == "done" else ShopRequest.created_at
    if date_from:
        stmt = stmt.where(date_col >= day_start(valid_day(date_from, "Von")))
    if date_to:
        stmt = stmt.where(date_col <= day_end(valid_day(date_to, "Bis")))
    order = ShopRequest.done_at.desc() if state == "done" else ShopRequest.created_at.desc()
    return list(db.scalars(stmt.order_by(order).limit(2000)))


def _out(db: Session, req: ShopRequest) -> dict:
    return request_out(req, project_names(db, [req.project_id] if req.project_id else []),
                       _image_map(db, {req.catalog_id}).get(req.catalog_id, ""))


@router.get("/requests")
def list_requests(
    project_id: int | None = None, all_projects: bool = True, state: str = Query("open", pattern="^(open|packed|done|all)$"),
    q: str = "", date_from: str = "", date_to: str = "",
    user: User = Depends(current_user), db: Session = Depends(get_db),
) -> list[dict]:
    rows = _filtered(db, user, project_id, all_projects, state, q, date_from, date_to)
    names = project_names(db, [r.project_id for r in rows if r.project_id])
    images = _image_map(db, {r.catalog_id for r in rows})
    return [request_out(r, names, images.get(r.catalog_id, "")) for r in rows]


@router.post("/requests", status_code=201)
def create_request(body: RequestIn, request: Request, user: User = Depends(current_user), db: Session = Depends(get_db)) -> dict:
    check_scope(db, user, body.project_id, "editor")
    title, article_no, unit = body.title.strip(), body.article_no.strip(), body.unit.strip()
    if body.catalog_id is not None:
        item = _item(db, body.catalog_id)
        title, article_no, unit = title or item.name, article_no or item.article_no, unit or item.unit
    if not title:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Bezeichnung fehlt.")
    req = ShopRequest(project_id=body.project_id, catalog_id=body.catalog_id, title=title, article_no=article_no,
                      unit=unit or "Stk", qty=body.qty, kind=body.kind, due=valid_day(body.due) if body.due else "",
                      note=body.note.strip(), requested_by=user.username)
    db.add(req)
    db.flush()
    audit.record(db, request, "shop_requested", user, f"shop:{req.id}", {"title": title, "project": body.project_id})
    db.commit()
    return _out(db, req)


def _req(db: Session, user: User, req_id: int) -> ShopRequest:
    req = db.get(ShopRequest, req_id)
    if req is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Eintrag nicht gefunden.")
    check_scope(db, user, req.project_id, "editor")
    return req


@router.patch("/requests/{req_id}")
def patch_request(req_id: int, body: RequestPatch, user: User = Depends(current_user), db: Session = Depends(get_db)) -> dict:
    req = _req(db, user, req_id)
    data = body.model_dump(exclude_none=True)
    if data.get("due"):
        valid_day(data["due"])
    for key, value in data.items():
        setattr(req, key, value.strip() if isinstance(value, str) else value)
    db.commit()
    return _out(db, req)


@router.post("/requests/{req_id}/pack")
def pack(req_id: int, body: Flag, user: User = Depends(current_user), db: Session = Depends(get_db)) -> dict:
    """Gepackt-Häkchen setzen oder entfernen (mit Name und Zeit)."""
    req = _req(db, user, req_id)
    req.packed_by, req.packed_at = (user.username, utcnow()) if body.value else ("", None)
    db.commit()
    return _out(db, req)


@router.post("/requests/{req_id}/done")
def done(req_id: int, body: Flag, user: User = Depends(current_user), db: Session = Depends(get_db)) -> dict:
    """Abhaken (mitgebracht/geprüft). Der Eintrag wandert damit ins Archiv; Entfernen holt ihn zurück."""
    req = _req(db, user, req_id)
    req.done_by, req.done_at = (user.username, utcnow()) if body.value else ("", None)
    db.commit()
    return _out(db, req)


@router.delete("/requests/{req_id}", status_code=204)
def delete_request(req_id: int, request: Request, user: User = Depends(current_user), db: Session = Depends(get_db)) -> None:
    req = _req(db, user, req_id)
    audit.record(db, request, "shop_deleted", user, f"shop:{req.id}", {"title": req.title})
    db.delete(req)
    db.commit()


# ---- Auswertung ----

@router.get("/summary")
def summary(
    project_id: int | None = None, all_projects: bool = True, date_from: str = "", date_to: str = "",
    user: User = Depends(current_user), db: Session = Depends(get_db), settings: Settings = Depends(get_settings),
) -> dict:
    """Archiv-Auswertung der abgehakten Einträge: je Artikel, je Monat, je Person, je Projekt."""
    rows = _filtered(db, user, project_id, all_projects, "done", "", date_from, date_to)
    names = project_names(db, [r.project_id for r in rows if r.project_id])
    tz = tzinfo(settings)

    def bucket(key_of) -> dict:
        out: dict = {}
        for r in rows:
            entry = out.setdefault(key_of(r), {"count": 0, "qty": 0.0})
            entry["count"] += 1
            entry["qty"] += r.qty
        return out

    by_item = bucket(lambda r: (r.title, r.article_no, r.unit))
    return {
        "total": len(rows),
        "by_item": sorted(({"title": k[0], "article_no": k[1], "unit": k[2], **v} for k, v in by_item.items()),
                          key=lambda e: (-e["count"], e["title"])),
        "by_month": sorted(({"period": k, **v} for k, v in bucket(lambda r: to_local(r.done_at, tz).strftime("%Y-%m")).items()),
                           key=lambda e: e["period"]),
        "by_user": sorted(({"user": k, **v} for k, v in bucket(lambda r: r.done_by or "-").items()), key=lambda e: -e["count"]),
        "by_project": sorted(({"project": k, **v} for k, v in bucket(lambda r: names.get(r.project_id, "Ohne Projekt")).items()),
                             key=lambda e: -e["count"]),
    }


@router.get("/export")
def export(
    project_id: int | None = None, all_projects: bool = True, state: str = Query("done", pattern="^(open|packed|done|all)$"),
    date_from: str = "", date_to: str = "",
    user: User = Depends(current_user), db: Session = Depends(get_db), settings: Settings = Depends(get_settings),
) -> Response:
    rows = _filtered(db, user, project_id, all_projects, state, "", date_from, date_to)
    names = project_names(db, [r.project_id for r in rows if r.project_id])
    tz = tzinfo(settings)
    wb = Workbook()
    ws = wb.active
    ws.title = "Einkauf"
    ws.append(["Projekt", "Bezeichnung", "Artikelnummer", "Menge", "Einheit", "Art", "Angefordert von", "Angefordert am",
               "Gepackt von", "Gepackt am", "Abgehakt von", "Abgehakt am", "Notiz"])

    def fmt(value) -> str:
        local = to_local(value, tz)
        return local.strftime("%d.%m.%Y %H:%M") if local else ""

    for r in rows:
        ws.append([names.get(r.project_id, ""), r.title, r.article_no, r.qty, r.unit,
                   "prüfen" if r.kind == "pruefen" else "mitbringen", r.requested_by, fmt(r.created_at),
                   r.packed_by, fmt(r.packed_at), r.done_by, fmt(r.done_at), r.note])
    buf = io.BytesIO()
    wb.save(buf)
    return Response(buf.getvalue(), media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    headers={"Content-Disposition": 'attachment; filename="einkauf.xlsx"'})
