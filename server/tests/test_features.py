"""Konflikte, Werkzeuge (Suche/KMK/Schrank...), Abhaken, Vorlagen, Sicherungen, Übersicht, Berichte."""
import io
import zipfile

from tests.test_api import MAPPING, login, make_user, rows


def setup_cable(admin, dataset, extra=None):
    mapping = {**MAPPING, **(extra or {})}
    r = admin.patch(f"/api/datasets/{dataset['id']}", json={"settings": {"mapping": mapping}})
    assert r.status_code == 200, r.text
    return r.json()


def row_id(admin, dataset_id, name):
    return next(r["id"] for r in rows(admin, dataset_id)["rows"] if r["data"]["Kabel"] == name)


def push(c, dataset_id, ops):
    r = c.post(f"/api/datasets/{dataset_id}/sync", json={"ops": ops})
    assert r.status_code == 200, r.text
    return r.json()


# ---- Konflikte ----

def test_conflict_is_recorded_and_resolved(admin, dataset):
    bob = make_user(admin)
    pid = dataset["project_id"]
    setup_cable(admin, dataset)
    admin.put(f"/api/projects/{pid}/members", json={"username": "bob", "role": "editor"})
    rid = row_id(admin, dataset["id"], "W1")
    base = rows(admin, dataset["id"])["rows"][0]
    push(admin, dataset["id"], [{"id": rid, "base_rev": base["rev"], "patch": {"Ist": 11}, "base": {"Ist": None}}])
    out = push(bob, dataset["id"], [{"id": rid, "base_rev": base["rev"], "patch": {"Ist": 12}, "base": {"Ist": None}}])
    assert out["results"][0]["status"] == "conflict"
    pending = admin.get(f"/api/datasets/{dataset['id']}/conflicts").json()
    assert len(pending) == 1
    c = pending[0]
    assert (c["server_value"], c["proposed_value"], c["server_by"], c["proposed_by"]) == (11, 12, "admin", "bob")
    assert admin.get(f"/api/projects/{pid}/conflicts").json()[0]["label"] == "W1"
    done = admin.post(f"/api/conflicts/{c['id']}/resolve", json={"choice": "proposed"}).json()
    assert done["status"] == "resolved"
    assert rows(admin, dataset["id"])["rows"][0]["data"]["Ist"] == 12
    assert admin.get(f"/api/datasets/{dataset['id']}/conflicts").json() == []
    assert admin.post(f"/api/conflicts/{c['id']}/resolve", json={"choice": "server"}).status_code == 409


def test_conflict_keep_server_value(admin, dataset):
    bob = make_user(admin)
    admin.put(f"/api/projects/{dataset['project_id']}/members", json={"username": "bob", "role": "editor"})
    rid = row_id(admin, dataset["id"], "W2")
    push(admin, dataset["id"], [{"id": rid, "base_rev": 1, "patch": {"Ist": 5}, "base": {"Ist": None}}])
    push(bob, dataset["id"], [{"id": rid, "base_rev": 1, "patch": {"Ist": 6}, "base": {"Ist": None}}])
    cid = admin.get(f"/api/datasets/{dataset['id']}/conflicts").json()[0]["id"]
    admin.post(f"/api/conflicts/{cid}/resolve", json={"choice": "server"})
    assert next(r for r in rows(admin, dataset["id"])["rows"] if r["data"]["Kabel"] == "W2")["data"]["Ist"] == 5


# ---- Werkzeuge ----

def test_search_preview_and_export(admin, dataset):
    r = admin.post(f"/api/datasets/{dataset['id']}/tools/search/preview", json={"config": {}, "term": "5x2"})
    assert r.status_code == 200, r.text
    table = r.json()["table"]
    assert table["total"] == 2 and "Kabel" in [c["name"] for c in table["columns"]]
    x = admin.post(f"/api/datasets/{dataset['id']}/tools/search/export", json={"term": "5x2", "formats": ["xlsx"]})
    assert x.status_code == 200 and x.content[:2] == b"PK"
    both = admin.post(f"/api/datasets/{dataset['id']}/tools/search/export", json={"term": "5x2", "formats": ["xlsx", "pdf"]})
    assert zipfile.ZipFile(io.BytesIO(both.content)).namelist().__len__() == 2


def test_batch_with_result_column(admin, dataset):
    cfg = {"batch_search_terms": [{"term": "W1"}, {"term": "W3"}],
           "batch": {"result_column_enabled": True, "result_column_name": "Treffer"}}
    prev = admin.post(f"/api/datasets/{dataset['id']}/tools/batch/preview", json={"config": cfg, "term": "W1"}).json()
    assert [t["count"] for t in prev["terms"]] == [1, 1]
    assert "Treffer" in [c["name"] for c in prev["table"]["columns"]]
    x = admin.post(f"/api/datasets/{dataset['id']}/tools/batch/export", json={"config": cfg, "formats": ["xlsx"]})
    assert len(zipfile.ZipFile(io.BytesIO(x.content)).namelist()) == 2


def test_highlight_colors(admin, dataset):
    cfg = {"colors": [{"id": 1, "name": "Gelb", "color_hex": "#FFFF00", "alpha": 30}],
           "color_search_terms": [{"term": "W3", "color_id": 1}], "color_min_matches": 1}
    t = admin.post(f"/api/datasets/{dataset['id']}/tools/highlight/preview", json={"config": cfg}).json()["table"]
    assert t["total"] == 4 and any(r["color"] for r in t["rows"])


def test_cabinet_detection_and_combined(admin, dataset):
    cfg = {"cabinet_config": {"formats": [{"pattern": "-XX", "enabled": True}]},
           "columns": [{"name": "BMK", "search_enabled": True}, {"name": "Kabel", "output_enabled": True}]}
    admin.patch(f"/api/datasets/{dataset['id']}", json={"add_columns": ["BMK"]})
    rid = row_id(admin, dataset["id"], "W1")
    push(admin, dataset["id"], [{"id": rid, "base_rev": 1, "patch": {"BMK": "-SC15"}, "base": {}}])
    prev = admin.post(f"/api/datasets/{dataset['id']}/tools/cabinet/preview", json={"config": cfg}).json()
    assert [c["name"] for c in prev["cabinets"]] == ["SC15"], prev
    x = admin.post(f"/api/datasets/{dataset['id']}/tools/cabinet/export",
                   json={"config": cfg, "formats": ["xlsx"], "combined": True})
    assert x.status_code == 200 and x.content[:2] == b"PK"


def test_unknown_tool_and_viewer_can_preview(admin, dataset):
    assert admin.post(f"/api/datasets/{dataset['id']}/tools/foo/preview", json={}).status_code == 404


# ---- KMK abhaken ----

def kmk_cfg():
    return {"batch_search_terms": [{"term": "3x1"}],
            "kmk_config": {"include_reste": True}}


def test_kmk_export_and_mark_later(admin, dataset):
    cfg = kmk_cfg()
    prev = admin.post(f"/api/datasets/{dataset['id']}/tools/kmk/preview", json={"config": cfg}).json()
    assert prev["labels"] >= 2 and len(prev["row_ids"]) == 2
    x = admin.post(f"/api/datasets/{dataset['id']}/tools/kmk/export", json={"config": cfg, "formats": ["pdf"]})
    assert x.status_code == 200 and x.content[:4] == b"%PDF"
    run_id = int(x.headers["x-run-id"])
    runs = admin.get(f"/api/datasets/{dataset['id']}/kmk/runs").json()
    assert runs[0]["id"] == run_id and runs[0]["status"] == {}
    m = admin.post(f"/api/kmk/runs/{run_id}/mark", json={"targets": ["1"]}).json()
    assert m["changed"] == 2 and m["status"]["1"]
    ds = admin.get(f"/api/datasets/{dataset['id']}").json()
    assert ds["settings"]["mapping"]["labeled1"] == "beschriftet Ziel 1"
    assert "beschriftet Ziel 2" in ds["columns"]
    data = rows(admin, dataset["id"])["rows"]
    assert sum(1 for r in data if r["data"].get("beschriftet Ziel 1")) == 2
    # nicht erneut ausgeben, was schon beschriftet ist
    again = admin.post(f"/api/datasets/{dataset['id']}/tools/kmk/preview",
                       json={"config": cfg, "hide_labeled": "1"}).json()
    assert again["labels"] == 0
    un = admin.post(f"/api/kmk/runs/{run_id}/mark", json={"targets": ["1"], "unmark": True}).json()
    assert un["status"]["1"] == ""


def test_kmk_auto_mark_both(admin, dataset):
    x = admin.post(f"/api/datasets/{dataset['id']}/tools/kmk/export",
                   json={"config": kmk_cfg(), "formats": ["xlsx"], "mark": "both"})
    assert x.status_code == 200
    data = rows(admin, dataset["id"])["rows"]
    marked = [r for r in data if r["data"].get("beschriftet Ziel 1") and r["data"].get("beschriftet Ziel 2")]
    assert len(marked) == 2


def test_viewer_cannot_mark(admin, dataset):
    bob = make_user(admin)
    admin.put(f"/api/projects/{dataset['project_id']}/members", json={"username": "bob", "role": "viewer"})
    x = admin.post(f"/api/datasets/{dataset['id']}/tools/kmk/export", json={"config": kmk_cfg(), "formats": ["pdf"]})
    run_id = int(x.headers["x-run-id"])
    assert bob.post(f"/api/kmk/runs/{run_id}/mark", json={"targets": ["1"]}).status_code == 403


# ---- Vorlagen ----

def test_templates_visible_to_all_editable_by_owner(admin):
    bob = make_user(admin)
    t = admin.post("/api/templates", json={"name": "Siemens", "tab_id": "kmk", "data": {"x": 1}}).json()
    assert t["path"] == "Vorlagen/admin/Siemens" and t["editable"]
    seen = bob.get("/api/templates", params={"tab_id": "kmk"}).json()
    assert seen[0]["path"] == "Vorlagen/admin/Siemens" and seen[0]["editable"] is False
    assert bob.get(f"/api/templates/{t['id']}").json()["data"] == {"x": 1}
    assert bob.put(f"/api/templates/{t['id']}", json={"name": "x", "tab_id": "kmk", "data": {}}).status_code == 403
    assert bob.delete(f"/api/templates/{t['id']}").status_code == 403
    own = bob.post("/api/templates", json={"name": "Siemens", "tab_id": "kmk", "data": {"y": 2}}).json()
    assert own["path"] == "Vorlagen/bob/Siemens"
    assert admin.delete(f"/api/templates/{own['id']}").status_code == 204  # Admin darf alles
    assert admin.post("/api/templates", json={"name": "a", "tab_id": "nope", "data": {}}).status_code == 422


# ---- Sicherungen ----

def test_backup_compare_restore(admin, dataset):
    first = admin.post("/api/admin/backups", json={}).json()
    assert first["summary"]["rows"] == 4
    rid = row_id(admin, dataset["id"], "W1")
    push(admin, dataset["id"], [{"id": rid, "base_rev": 1, "patch": {"Ist": 99}, "base": {"Ist": None}}])
    diff = admin.post("/api/admin/backups/compare", json={"old": first["id"]}).json()
    change = diff["datasets"][0]["changes"][0]
    assert (change["row"], change["field"], change["new"]) == (1, "Ist", 99)
    second = admin.post("/api/admin/backups", json={}).json()
    assert admin.post("/api/admin/backups/compare", json={"old": first["id"], "new": second["id"]}).json()["totals"]["changed_cells"] == 1
    slug = admin.get(f"/api/projects/{dataset['project_id']}").json()["slug"]
    res = admin.post(f"/api/admin/backups/{first['id']}/restore", json={"project": slug})
    assert res.status_code == 200 and res.json()["rows"] == 4
    data = rows(admin, dataset["id"])["rows"]
    assert len(data) == 4 and all(r["data"].get("Ist") is None for r in data)
    kinds = [b["kind"] for b in admin.get("/api/admin/backups").json()["backups"]]
    assert "pre-restore" in kinds
    down = admin.get(f"/api/admin/backups/{first['id']}/download")
    assert down.status_code == 200 and zipfile.ZipFile(io.BytesIO(down.content)).testzip() is None
    up = admin.post("/api/admin/backups/upload", files={"file": ("alt.zip", down.content)})
    assert up.status_code == 201
    assert admin.post("/api/admin/backups/upload", files={"file": ("kaputt.zip", b"nein")}).status_code == 422


def test_backups_admin_only(admin):
    bob = make_user(admin)
    assert bob.get("/api/admin/backups").status_code == 403


# ---- Übersicht, Prognose, Bericht ----

def fill(admin, dataset):
    admin.patch(f"/api/datasets/{dataset['id']}", json={"add_columns": ["Ziel 1", "Ziel 2"]})
    setup_cable(admin, dataset, {"target1": "Ziel 1", "target2": "Ziel 2"})
    ops = []
    for name, ist, z1, z2, date in [("W1", 12, "A", "B", "21.10.26"), ("W2", None, "B", "A", None),
                                    ("W3", 25, "C", "D", "22.10.26"), ("W4", None, "X", "Y", None)]:
        patch = {"Ziel 1": z1, "Ziel 2": z2}
        if ist:
            patch.update({"Ist": ist, "Datum": date})
        ops.append({"id": row_id(admin, dataset["id"], name), "base_rev": 1, "patch": patch, "base": {}})
    push(admin, dataset["id"], ops)


def test_overview_forecast_and_report(admin, dataset):
    fill(admin, dataset)
    ov = admin.get(f"/api/projects/{dataset['project_id']}/overview").json()
    sections = {s["label"]: s for s in ov["datasets"][0]["sections"]}
    assert sections["3x1,5"]["done"] == 1 and sections["3x1,5"]["open"] == 1
    # W2 liegt auf derselben Strecke wie W1 (gedreht) -> Prognose 12 m
    f = admin.get(f"/api/datasets/{dataset['id']}/forecast").json()["rows"]
    assert f[str(row_id(admin, dataset["id"], "W2"))] == {"length": 12.0, "basis": "route"}
    w = admin.post(f"/api/datasets/{dataset['id']}/forecast/write", json={}).json()
    assert w["column"] == "prognostizierte Länge" and w["changed"] == 2
    assert next(r for r in rows(admin, dataset["id"])["rows"] if r["data"]["Kabel"] == "W2")["data"]["prognostizierte Länge"] == 12.0
    txt = admin.get(f"/api/datasets/{dataset['id']}/report.txt")
    body = txt.content.decode("utf-8-sig")
    assert "== 21.10.26 ==" in body and "3x1,5: 1 Kabel, 12 m" in body and "== Summe ==" in body
    assert "Tagesbericht" in txt.headers["content-disposition"]
    assert admin.get(f"/api/projects/{dataset['project_id']}/report.txt").status_code == 200
    assert admin.get(f"/api/datasets/{dataset['id']}/report.txt", params={"start": "bad"}).status_code == 422


# ---- Notizen, Löschen ----

def _project(admin) -> int:
    return admin.post("/api/projects", json={"name": "Notizen-Test"}).json()["id"]


def test_notes_crud_and_version_conflict(admin):
    pid = _project(admin)
    created = admin.post(f"/api/projects/{pid}/notes", json={"title": "Plan", "body": "# Hallo\n- a"})
    assert created.status_code == 201 and created.json()["version"] == 1
    nid = created.json()["id"]
    listing = admin.get(f"/api/projects/{pid}/notes").json()
    assert listing[0]["title"] == "Plan" and "body" not in listing[0] and listing[0]["preview"].startswith("# Hallo")
    saved = admin.put(f"/api/projects/{pid}/notes/{nid}", json={"title": "Plan", "body": "neu", "version": 1})
    assert saved.json()["version"] == 2 and saved.json()["body"] == "neu"
    stale = admin.put(f"/api/projects/{pid}/notes/{nid}", json={"title": "Plan", "body": "alt", "version": 1})
    assert stale.status_code == 409
    assert admin.delete(f"/api/projects/{pid}/notes/{nid}").status_code == 204
    assert admin.get(f"/api/projects/{pid}/notes").json() == []


def test_notes_viewer_cannot_write(admin, client):
    pid = _project(admin)
    admin.post("/api/admin/users", json={"username": "lese", "password": "lese-passwort-123", "role": "user"})
    admin.put(f"/api/projects/{pid}/members", json={"username": "lese", "role": "viewer"})
    note = admin.post(f"/api/projects/{pid}/notes", json={"title": "x", "body": "y"}).json()
    assert client.post("/api/auth/login", json={"username": "lese", "password": "lese-passwort-123"}).status_code == 200
    assert client.get(f"/api/projects/{pid}/notes/{note['id']}").status_code == 200
    assert client.post(f"/api/projects/{pid}/notes", json={"title": "z"}).status_code == 403
    assert client.delete(f"/api/projects/{pid}/notes/{note['id']}").status_code == 403


def test_delete_project_removes_everything(admin, tmp_path):
    from sqlalchemy import func, select

    from wtserver.db import SessionLocal
    from wtserver.models import Note, Row

    pid = _project(admin)
    admin.post(f"/api/projects/{pid}/notes", json={"title": "n"})
    import pandas as pd
    path = tmp_path / "l.xlsx"
    pd.DataFrame({"A": [1, 2, 3]}).to_excel(path, index=False)
    with path.open("rb") as handle:
        assert admin.post(f"/api/projects/{pid}/files", files={"file": ("l.xlsx", handle)}).status_code == 201
    assert admin.post(f"/api/projects/{pid}/datasets", json={"file": "l.xlsx"}).status_code == 201
    assert admin.delete(f"/api/projects/{pid}").status_code == 204
    with SessionLocal() as db:
        assert db.scalar(select(func.count()).select_from(Row)) == 0
        assert db.scalar(select(func.count()).select_from(Note)) == 0
    assert admin.get("/api/projects").json() == []


# ---- Übersetzer ----

def _translate_setup(admin, tmp_path):
    import pandas as pd

    pid = admin.post("/api/projects", json={"name": "Translate"}).json()["id"]
    ziel = tmp_path / "ziel.xlsx"
    quelle = tmp_path / "quelle.xlsx"
    pd.DataFrame({"Kabel": ["K1", "K2", "K3", "K4"], "W-Nr": ["W-001", "w 002", "W-003", None],
                  "Notiz": ["alt", None, "bleibt", "x"]}).to_excel(ziel, index=False)
    pd.DataFrame({"Nummer": ["W001", "W002", "W002", "W099"], "Ort": ["Halle 1", "Halle 2", "Halle 2b", "Keller"],
                  "Prio": [1, 2, 3, 4]}).to_excel(quelle, index=False)
    for path in (ziel, quelle):
        with path.open("rb") as handle:
            assert admin.post(f"/api/projects/{pid}/files", files={"file": (path.name, handle)}).status_code == 201
    ds = admin.post(f"/api/projects/{pid}/datasets", json={"file": "ziel.xlsx"}).json()["id"]
    return pid, ds


def _body(**extra):
    body = {"source": {"kind": "file", "file": "quelle.xlsx"}, "key_a": "W-Nr", "key_b": "Nummer",
            "ignore_separators": True,
            "mappings": [{"source": "Ort", "target": "Standort"}, {"source": "Prio", "target": "Notiz", "mode": "empty"}]}
    body.update(extra)
    return body


def test_translate_preview_apply_and_export(admin, tmp_path):
    pid, ds = _translate_setup(admin, tmp_path)
    src = admin.get(f"/api/datasets/{ds}/translate/sources").json()
    assert src["files"] == ["quelle.xlsx", "ziel.xlsx"] and src["datasets"] == []
    info = admin.post(f"/api/datasets/{ds}/translate/source", json={"kind": "file", "file": "quelle.xlsx"}).json()
    assert info["columns"] == ["Nummer", "Ort", "Prio"] and info["total"] == 4

    pre = admin.post(f"/api/datasets/{ds}/translate/preview", json=_body()).json()
    stats = pre["stats"]
    # K1 (W-001) und K2 (w 002) finden einen Treffer, K3 (W-003) nicht, K4 hat keinen Schlüssel
    assert (stats["matched"], stats["unmatched"], stats["empty_key"], stats["duplicate_keys"]) == (2, 1, 1, 1)
    assert pre["new_columns"] == ["Standort"] and pre["unmatched_keys"] == ["W-003"]
    assert stats["changed_cells"] == 3  # Standort K1 und K2, Notiz K2 (war leer; K1 hat "alt" und bleibt)

    excel = admin.post(f"/api/datasets/{ds}/translate/export", json=_body(duplicates="last"))
    assert excel.status_code == 200 and excel.content[:2] == b"PK"
    assert admin.get(f"/api/datasets/{ds}").json()["columns"] == ["Kabel", "W-Nr", "Notiz"]  # Export ändert nichts

    done = admin.post(f"/api/datasets/{ds}/translate/apply", json=_body(duplicates="last"))
    assert done.status_code == 200 and done.json()["new_columns"] == ["Standort"]
    rows = admin.get(f"/api/datasets/{ds}/rows?since=0").json()
    by_cable = {r["data"]["Kabel"]: r["data"] for r in rows["rows"]}
    assert by_cable["K1"]["Standort"] == "Halle 1" and by_cable["K1"]["Notiz"] == "alt"  # "nur leere" lässt "alt" stehen
    assert by_cable["K2"]["Standort"] == "Halle 2b" and by_cable["K2"]["Notiz"] == 3  # letzter Treffer, Notiz war leer
    assert by_cable["K3"].get("Standort") is None and by_cable["K3"]["Notiz"] == "bleibt"  # nicht angefasst


def test_translate_skip_duplicates_and_validation(admin, tmp_path):
    _, ds = _translate_setup(admin, tmp_path)
    pre = admin.post(f"/api/datasets/{ds}/translate/preview", json=_body(duplicates="skip")).json()
    assert pre["stats"]["ambiguous"] == 1 and pre["stats"]["matched"] == 1
    bad = admin.post(f"/api/datasets/{ds}/translate/preview", json=_body(key_b="gibtsnicht"))
    assert bad.status_code == 422
    clash = admin.post(f"/api/datasets/{ds}/translate/preview",
                       json=_body(mappings=[{"source": "Ort", "target": "W-Nr"}]))
    assert clash.status_code == 422
    missing = admin.post(f"/api/datasets/{ds}/translate/preview", json=_body(source={"kind": "file", "file": "../x.xlsx"}))
    assert missing.status_code in (400, 404, 422)


def test_translate_viewer_cannot_apply(admin, client, tmp_path):
    pid, ds = _translate_setup(admin, tmp_path)
    admin.post("/api/admin/users", json={"username": "lese2", "password": "lese-passwort-123", "role": "user"})
    admin.put(f"/api/projects/{pid}/members", json={"username": "lese2", "role": "viewer"})
    assert client.post("/api/auth/login", json={"username": "lese2", "password": "lese-passwort-123"}).status_code == 200
    assert client.post(f"/api/datasets/{ds}/translate/preview", json=_body()).status_code == 200
    assert client.post(f"/api/datasets/{ds}/translate/apply", json=_body()).status_code == 403


# ---- Mehrere Blätter ----

def _workbook(admin, tmp_path):
    import pandas as pd

    pid = admin.post("/api/projects", json={"name": "Mappe"}).json()["id"]
    path = tmp_path / "mappe.xlsx"
    with pd.ExcelWriter(path) as writer:
        pd.DataFrame({"Kabel": ["A1", "A2"], "W-Nr": ["W-001", "W-002"]}).to_excel(writer, sheet_name="Halle", index=False)
        pd.DataFrame({"Zeile": ["B1", "B2", "B3"], "W-Nr": ["W-002", "W-003", "W-001"], "Extra": [1, 2, 3]}).to_excel(
            writer, sheet_name="Keller", index=False)
        pd.DataFrame().to_excel(writer, sheet_name="Leer", index=False)
    quelle = tmp_path / "quelle2.xlsx"
    pd.DataFrame({"Nummer": ["W001", "W002", "W003"], "Ort": ["O1", "O2", "O3"]}).to_excel(quelle, index=False)
    for p in (path, quelle):
        with p.open("rb") as handle:
            assert admin.post(f"/api/projects/{pid}/files", files={"file": (p.name, handle)}).status_code == 201
    return pid


def test_import_all_sheets_and_export_workbook(admin, tmp_path):
    import io

    import pandas as pd

    pid = _workbook(admin, tmp_path)
    assert admin.get(f"/api/projects/{pid}/files/mappe.xlsx/sheets").json()["sheets"] == ["Halle", "Keller", "Leer"]
    ds = admin.post(f"/api/projects/{pid}/datasets", json={"file": "mappe.xlsx", "mode": "all"})
    assert ds.status_code == 201
    meta = ds.json()
    assert meta["columns"] == ["Blatt", "Kabel", "W-Nr", "Zeile", "Extra"]
    assert [s["name"] for s in meta["settings"]["sheets"]] == ["Halle", "Keller"]  # leeres Blatt entfällt
    rows = admin.get(f"/api/datasets/{meta['id']}/rows?since=0").json()["rows"]
    assert [r["data"]["Blatt"] for r in rows] == ["Halle", "Halle", "Keller", "Keller", "Keller"]

    # Übersetzer nur im Blatt „Keller“, neue Spalte; Export liefert wieder zwei Blätter
    body = {"source": {"kind": "file", "file": "quelle2.xlsx"}, "key_a": "W-Nr", "key_b": "Nummer",
            "ignore_separators": True, "sheets": ["Keller"], "mappings": [{"source": "Ort", "target": "Standort"}]}
    pre = admin.post(f"/api/datasets/{meta['id']}/translate/preview", json=body).json()
    assert pre["stats"]["rows"] == 3 and pre["stats"]["matched"] == 3 and pre["stats"]["changed_cells"] == 3
    assert admin.post(f"/api/datasets/{meta['id']}/translate/apply", json=body).status_code == 200
    export = admin.get(f"/api/datasets/{meta['id']}/export")
    workbook = pd.read_excel(io.BytesIO(export.content), sheet_name=None)
    assert list(workbook) == ["Halle", "Keller"]
    assert list(workbook["Halle"].columns) == ["Kabel", "W-Nr"]  # Halle unberührt, keine neue Spalte
    assert list(workbook["Keller"].columns) == ["Zeile", "W-Nr", "Extra", "Standort"]
    assert list(workbook["Keller"]["Standort"]) == ["O2", "O3", "O1"]


def test_import_single_sheet_and_source_sheet(admin, tmp_path):
    pid = _workbook(admin, tmp_path)
    ds = admin.post(f"/api/projects/{pid}/datasets", json={"file": "mappe.xlsx", "mode": "sheet", "sheet": "Keller"}).json()
    assert ds["columns"] == ["Zeile", "W-Nr", "Extra"] and ds["name"] == "mappe - Keller" and ds["settings"] == {}
    first = admin.post(f"/api/projects/{pid}/datasets", json={"file": "mappe.xlsx"}).json()
    assert first["columns"] == ["Kabel", "W-Nr"]  # Standard: erstes Blatt wie bisher
    info = admin.post(f"/api/datasets/{first['id']}/translate/source", json={"kind": "file", "file": "mappe.xlsx", "sheet": "Keller"}).json()
    assert info["columns"] == ["Zeile", "W-Nr", "Extra"] and info["sheets"] == ["Halle", "Keller", "Leer"]


def test_csv_source(admin, tmp_path):
    pid = admin.post("/api/projects", json={"name": "Csv"}).json()["id"]
    csv = tmp_path / "q.csv"
    csv.write_text("Nummer;Ort\nW1;Köln\nW2;Bonn\n", encoding="cp1252")
    with csv.open("rb") as handle:
        assert admin.post(f"/api/projects/{pid}/files", files={"file": ("q.csv", handle)}).status_code == 201
    ds = admin.post(f"/api/projects/{pid}/datasets", json={"file": "q.csv"})
    assert ds.status_code == 201 and ds.json()["columns"] == ["Nummer", "Ort"]


# ---- Verlauf und Rückgängig ----

def test_history_and_undo_translate_run(admin, tmp_path):
    pid, ds = _translate_setup(admin, tmp_path)
    done = admin.post(f"/api/datasets/{ds}/translate/apply", json=_body()).json()
    batch = done["batch"]
    history = admin.get(f"/api/datasets/{ds}/history").json()
    mine = [c for c in history["changes"] if c["batch"] == batch]
    assert len(mine) == 3 and {c["kind"] for c in mine} == {"translate"} and history["undone"] == []
    assert mine[0]["label"].startswith("K")

    # K1 danach von Hand ändern: dieser Wert darf beim Rückgängig nicht überschrieben werden
    rows = admin.get(f"/api/datasets/{ds}/rows?since=0").json()["rows"]
    k1 = next(r for r in rows if r["data"]["Kabel"] == "K1")
    sync = admin.post(f"/api/datasets/{ds}/sync", json={"ops": [
        {"id": k1["id"], "base_rev": k1["rev"], "patch": {"Standort": "von Hand"}, "base": {"Standort": "Halle 1"}}]})
    assert sync.status_code == 200
    undo = admin.post(f"/api/datasets/{ds}/history/batches/{batch}/undo").json()
    assert undo["cells"] == 2 and undo["skipped"] == 1
    rows = {r["data"]["Kabel"]: r["data"] for r in admin.get(f"/api/datasets/{ds}/rows?since=0").json()["rows"]}
    assert rows["K1"]["Standort"] == "von Hand"          # neuer als der Lauf: bleibt
    assert rows["K2"].get("Standort") in (None, "") and rows["K2"].get("Notiz") in (None, "")
    assert admin.get(f"/api/datasets/{ds}/history").json()["undone"] == [batch]
    assert admin.post(f"/api/datasets/{ds}/history/batches/{batch}/undo").status_code == 409


def test_revert_single_change(admin, tmp_path):
    _, ds = _translate_setup(admin, tmp_path)
    rows = admin.get(f"/api/datasets/{ds}/rows?since=0").json()["rows"]
    k3 = next(r for r in rows if r["data"]["Kabel"] == "K3")
    admin.post(f"/api/datasets/{ds}/sync", json={"ops": [
        {"id": k3["id"], "base_rev": k3["rev"], "patch": {"Notiz": "neu"}, "base": {"Notiz": "bleibt"}}]})
    change = admin.get(f"/api/datasets/{ds}/history").json()["changes"][0]
    assert (change["field"], change["old"], change["new"]) == ("Notiz", "bleibt", "neu")
    assert admin.post(f"/api/datasets/{ds}/history/changes/{change['id']}/revert").status_code == 200
    again = admin.post(f"/api/datasets/{ds}/history/changes/{change['id']}/revert")
    assert again.status_code == 409  # Wert ist schon zurückgesetzt
