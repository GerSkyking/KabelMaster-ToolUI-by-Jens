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
