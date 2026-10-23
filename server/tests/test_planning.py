"""Einkauf/Packliste, Whiteboard, Tagesbericht, Zeitplan."""
import io
from datetime import date

from tests.test_api import login
from wtserver import ics

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 32


def _project(admin, name="Plan-Test") -> int:
    return admin.post("/api/projects", json={"name": name}).json()["id"]


def _viewer(admin, pid):
    admin.post("/api/admin/users", json={"username": "lese", "password": "lese-passwort-123", "role": "user"})
    admin.put(f"/api/projects/{pid}/members", json={"username": "lese", "role": "viewer"})
    return login("lese", "lese-passwort-123")


def test_catalog_search_and_image(admin):
    item = admin.post("/api/shop/catalog", json={"name": "Kabeltrommel 50 m", "article_no": "KT-50", "category": "Werkzeug"}).json()
    admin.post("/api/shop/catalog", json={"name": "Schrauben M6", "article_no": "S-M6"})
    assert [i["name"] for i in admin.get("/api/shop/catalog", params={"q": "kt-50"}).json()] == ["Kabeltrommel 50 m"]
    assert admin.get("/api/shop/categories").json() == ["Werkzeug"]
    bad = admin.put(f"/api/shop/catalog/{item['id']}/image", files={"file": ("x.svg", b"<svg onload=alert(1)>", "image/svg+xml")})
    assert bad.status_code == 400
    ok = admin.put(f"/api/shop/catalog/{item['id']}/image", files={"file": ("a.png", PNG, "image/png")})
    assert ok.status_code == 200 and ok.json()["image_url"]
    got = admin.get(ok.json()["image_url"])
    assert got.status_code == 200 and got.content == PNG and "private" in got.headers["cache-control"]


def test_request_flow_pack_done_archive_and_summary(admin):
    pid = _project(admin)
    item = admin.post("/api/shop/catalog", json={"name": "Kabelbinder", "article_no": "KB-1"}).json()
    r = admin.post("/api/shop/requests", json={"catalog_id": item["id"], "qty": 3, "project_id": pid, "due": "2026-10-30"})
    assert r.status_code == 201 and r.json()["title"] == "Kabelbinder" and r.json()["article_no"] == "KB-1"
    rid = r.json()["id"]
    admin.post("/api/shop/requests", json={"title": "Prüfen: Leiter", "kind": "pruefen", "project_id": pid})
    assert len(admin.get("/api/shop/requests", params={"project_id": pid}).json()) == 2
    packed = admin.post(f"/api/shop/requests/{rid}/pack", json={"value": True}).json()
    assert packed["status"] == "packed" and packed["packed_by"] == "admin"
    assert len(admin.get("/api/shop/requests", params={"state": "packed"}).json()) == 1
    done = admin.post(f"/api/shop/requests/{rid}/done", json={"value": True}).json()
    assert done["status"] == "done" and done["done_by"] == "admin"
    assert [x["id"] for x in admin.get("/api/shop/requests", params={"state": "open"}).json()] != [rid]
    archive = admin.get("/api/shop/requests", params={"state": "done", "project_id": pid}).json()
    assert [x["title"] for x in archive] == ["Kabelbinder"]
    admin.delete(f"/api/shop/catalog/{item['id']}")  # Archiv behält Name und Artikelnummer
    summary = admin.get("/api/shop/summary", params={"project_id": pid}).json()
    assert summary["total"] == 1 and summary["by_item"][0]["qty"] == 3 and summary["by_item"][0]["article_no"] == "KB-1"
    assert summary["by_user"][0]["user"] == "admin" and len(summary["by_month"]) == 1
    export = admin.get("/api/shop/export", params={"project_id": pid})
    assert export.status_code == 200 and export.content[:2] == b"PK"
    assert admin.post(f"/api/shop/requests/{rid}/done", json={"value": False}).json()["status"] == "packed"


def test_shop_validation_and_permissions(admin):
    pid = _project(admin)
    assert admin.post("/api/shop/requests", json={"title": ""}).status_code == 422
    assert admin.post("/api/shop/requests", json={"title": "x", "due": "morgen"}).status_code == 422
    rid = admin.post("/api/shop/requests", json={"title": "Zange", "project_id": pid}).json()["id"]
    client = _viewer(admin, pid)
    assert len(client.get("/api/shop/requests", params={"project_id": pid}).json()) == 1
    assert client.post(f"/api/shop/requests/{rid}/done", json={"value": True}).status_code == 403
    assert client.post("/api/shop/requests", json={"title": "y", "project_id": pid}).status_code == 403
    assert client.post("/api/shop/requests", json={"title": "ohne Projekt"}).status_code == 201  # ohne Projekt darf jeder


def test_board_project_and_global(admin):
    pid = _project(admin)
    n = admin.post("/api/board", json={"project_id": pid, "text": "Kran bestellen", "color": "green", "x": 30, "y": 40}).json()
    admin.post("/api/board", json={"text": "Allgemein"})
    assert [x["text"] for x in admin.get("/api/board", params={"project_id": pid}).json()] == ["Kran bestellen"]
    assert [x["text"] for x in admin.get("/api/board").json()] == ["Allgemein"]
    moved = admin.patch(f"/api/board/{n['id']}", json={"x": 300, "y": 120}).json()
    assert moved["x"] == 300 and moved["text"] == "Kran bestellen"
    assert admin.post("/api/board", json={"text": "x", "color": "lila"}).status_code == 422
    client = _viewer(admin, pid)
    assert len(client.get("/api/board", params={"project_id": pid}).json()) == 1
    assert client.patch(f"/api/board/{n['id']}", json={"x": 1}).status_code == 403
    assert client.post("/api/board", json={"text": "global ok"}).status_code == 201
    assert admin.delete(f"/api/board/{n['id']}").status_code == 204


def test_worklog_private_and_summary(admin):
    pid = _project(admin)
    for day, hours in (("2026-10-19", 8), ("2026-10-20", 6.5), ("2026-11-02", 4)):
        assert admin.post("/api/worklog", json={"project_id": pid, "day": day, "text": "Kabel gezogen", "hours": hours}).status_code == 201
    assert admin.post("/api/worklog", json={"project_id": pid, "day": "20.10.2026", "text": "x"}).status_code == 422
    week = admin.get("/api/worklog/summary", params={"group": "week", "project_id": pid}).json()
    assert {w["period"]: w["hours"] for w in week} == {"2026-W43": 14.5, "2026-W45": 4}
    month = admin.get("/api/worklog/summary", params={"group": "month"}).json()
    assert {m["period"]: m["entries"] for m in month} == {"2026-10": 2, "2026-11": 1}
    year = admin.get("/api/worklog/summary", params={"group": "year"}).json()
    assert year[0]["hours"] == 18.5 and year[0]["days"] == 3
    assert admin.get("/api/worklog/export", params={"project_id": pid}).content[:2] == b"PK"
    # Einträge anderer sind unsichtbar
    client = _viewer(admin, pid)
    assert client.get("/api/worklog", params={"project_id": pid}).json() == []
    own = client.post("/api/worklog", json={"project_id": pid, "day": "2026-10-21", "text": "Lesen"}).json()
    other = admin.get("/api/worklog", params={"project_id": pid}).json()
    assert own["id"] not in [e["id"] for e in other]
    assert admin.delete(f"/api/worklog/{own['id']}").status_code == 404


def test_worklog_counts_own_edits(admin, dataset):
    from tests.test_features import push, row_id, setup_cable
    setup_cable(admin, dataset)
    rid = row_id(admin, dataset["id"], "W1")
    push(admin, dataset["id"], [{"id": rid, "base_rev": 1, "patch": {"Ist": 12}, "base": {}}])
    today = date.today().isoformat()
    summary = admin.get("/api/worklog/summary", params={"group": "day", "date_from": today, "date_to": today}).json()
    assert summary and summary[0]["edits"] >= 1


ICS = """BEGIN:VCALENDAR
BEGIN:VEVENT
SUMMARY:Urlaub Jens
DTSTART;VALUE=DATE:20261026
DTEND;VALUE=DATE:20261030
END:VEVENT
BEGIN:VEVENT
SUMMARY:Jour fixe
DTSTART:20261023T090000
RRULE:FREQ=WEEKLY;BYDAY=MO,FR;COUNT=5
EXDATE:20261026T090000
END:VEVENT
BEGIN:VEVENT
SUMMARY:Abgesagt
DTSTART:20261024T090000
STATUS:CANCELLED
END:VEVENT
END:VCALENDAR
"""


def test_ics_parser():
    events = ics.parse(ICS, date(2026, 10, 1), date(2026, 12, 31))
    urlaub = [e for e in events if e["title"] == "Urlaub Jens"][0]
    assert (urlaub["start"], urlaub["end"], urlaub["all_day"]) == ("2026-10-26", "2026-10-29", True)
    fixe = [e["start"] for e in events if e["title"] == "Jour fixe"]
    assert fixe == ["2026-10-23", "2026-10-30", "2026-11-02", "2026-11-06"]  # COUNT=5 inkl. ausgenommenem 26.10.
    assert not [e for e in events if e["title"] == "Abgesagt"]


def test_ics_blocks_internal_and_bad_urls():
    for url in ("http://127.0.0.1/x.ics", "http://localhost/x.ics", "file:///etc/passwd", "ftp://example.org/x"):
        try:
            ics.check_url(url, allow_private=False)
        except ics.FeedError:
            continue
        raise AssertionError(url)
    assert ics.check_url("webcal://example.org/x", allow_private=True) == "https://example.org/x"


def test_schedule_events_and_feed(admin, monkeypatch):
    pid = _project(admin)
    ev = admin.post("/api/schedule/events", json={"project_id": pid, "title": "Rohbau", "start": "2026-11-02", "end": "2026-11-13"})
    assert ev.status_code == 201
    admin.post("/api/schedule/events", json={"title": "Betriebsferien", "start": "2026-12-24", "end": "2026-12-31", "kind": "urlaub"})
    assert admin.post("/api/schedule/events", json={"project_id": pid, "title": "x", "start": "2026-11-05", "end": "2026-11-01"}).status_code == 422
    month = admin.get("/api/schedule", params={"start": "2026-11-01", "end": "2026-11-30", "project_id": pid}).json()
    assert [e["title"] for e in month["events"]] == ["Rohbau"]
    dec = admin.get("/api/schedule", params={"start": "2026-12-01", "end": "2026-12-31", "project_id": pid}).json()
    assert [e["title"] for e in dec["events"]] == ["Betriebsferien"]  # gemeinsamer Eintrag ohne Projekt
    done = admin.patch(f"/api/schedule/events/{ev.json()['id']}", json={"done": True}).json()
    assert done["done"] is True

    monkeypatch.setattr(ics, "fetch", lambda url, allow_private=False, timeout=8.0: ICS)
    monkeypatch.setattr(ics, "check_url", lambda url, allow_private=False: url)
    feed = admin.post("/api/schedule/feeds", json={"project_id": pid, "name": "Urlaub", "url": "https://cal.example.org/u.ics?token=geheim"})
    assert feed.status_code == 201 and "url" not in feed.json()
    cal = admin.get("/api/schedule", params={"start": "2026-10-26", "end": "2026-10-31", "project_id": pid}).json()
    assert any(e["title"] == "Urlaub Jens" for e in cal["feeds"][0]["events"])
    assert admin.post(f"/api/schedule/feeds/{feed.json()['id']}/refresh").json()["error"] == ""

    monkeypatch.setattr(ics, "fetch", lambda *a, **k: (_ for _ in ()).throw(ics.FeedError("kaputt")))
    assert admin.post("/api/schedule/feeds", json={"name": "Defekt", "url": "https://cal.example.org/x.ics"}).status_code == 422

    client = _viewer(admin, pid)
    assert client.get("/api/schedule", params={"start": "2026-11-01", "end": "2026-11-30", "project_id": pid}).status_code == 200
    assert client.post("/api/schedule/events", json={"project_id": pid, "title": "x", "start": "2026-11-05"}).status_code == 403


def test_delete_project_removes_planning_data(admin):
    pid = _project(admin)
    admin.post("/api/shop/requests", json={"title": "Zange", "project_id": pid})
    admin.post("/api/board", json={"project_id": pid, "text": "n"})
    admin.post("/api/worklog", json={"project_id": pid, "day": "2026-10-20", "text": "t"})
    admin.post("/api/schedule/events", json={"project_id": pid, "title": "e", "start": "2026-11-05"})
    assert admin.delete(f"/api/projects/{pid}").status_code == 204
    from wtserver.db import SessionLocal
    from wtserver.models import BoardNote, ScheduleEvent, ShopRequest, WorkLog
    with SessionLocal() as db:
        for model in (ShopRequest, BoardNote, WorkLog, ScheduleEvent):
            assert db.query(model).count() == 0
