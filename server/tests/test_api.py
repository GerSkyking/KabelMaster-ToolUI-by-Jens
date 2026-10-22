import io

import pandas as pd
from fastapi.testclient import TestClient

from wtserver.main import app

MAPPING = {"cable_id": "Kabel", "cross_section": "Querschnitt", "target_length": "Länge",
           "start": "Von", "end": "Bis", "pulled_length": "Ist", "date": "Datum"}


def login(username: str, password: str) -> TestClient:
    c = TestClient(app)
    r = c.post("/api/auth/login", json={"username": username, "password": password})
    assert r.status_code == 200, r.text
    return c


def make_user(admin: TestClient, name: str = "bob", role: str = "user") -> TestClient:
    r = admin.post("/api/admin/users", json={"username": name, "password": "bob-password-1", "role": role})
    assert r.status_code == 201, r.text
    return login(name, "bob-password-1")


def rows(c: TestClient, dataset_id: int, since: int = 0) -> dict:
    return c.get(f"/api/datasets/{dataset_id}/rows", params={"since": since}).json()


def test_health_and_auth_config(client):
    assert client.get("/api/health").json()["status"] == "ok"
    cfg = client.get("/api/auth/config").json()
    assert cfg["local"] is True and cfg["ldap"] is False and cfg["oidc"] is None


def test_login_required_and_wrong_password(client):
    assert client.get("/api/projects").status_code == 401
    assert client.post("/api/auth/login", json={"username": "admin", "password": "falsch"}).status_code == 401


def test_login_throttle(client):
    for _ in range(8):
        client.post("/api/auth/login", json={"username": "admin", "password": "x"})
    r = client.post("/api/auth/login", json={"username": "admin", "password": "admin-password-123"})
    assert r.status_code == 429


def test_session_cookie_is_httponly(client):
    r = client.post("/api/auth/login", json={"username": "admin", "password": "admin-password-123"})
    assert "httponly" in r.headers["set-cookie"].lower()
    assert client.get("/api/auth/me").json()["role"] == "admin"
    client.post("/api/auth/logout")
    assert client.get("/api/auth/me").status_code == 401


def test_import_and_rows(admin, dataset):
    assert dataset["columns"][:3] == ["Kabel", "Querschnitt", "Länge"]
    data = rows(admin, dataset["id"])
    assert len(data["rows"]) == 4
    assert data["rows"][0]["data"]["Kabel"] == "W1"
    assert data["rows"][0]["data"]["Länge"] == 10


def test_upload_rejects_bad_type_and_traversal(admin):
    pid = admin.post("/api/projects", json={"name": "P"}).json()["id"]
    assert admin.post(f"/api/projects/{pid}/files", files={"file": ("x.exe", b"abc")}).status_code == 400
    r = admin.post(f"/api/projects/{pid}/files", files={"file": ("../../evil.xlsx", b"abc")})
    assert r.status_code == 201 and r.json()["name"] == "evil.xlsx"
    assert admin.get(f"/api/projects/{pid}/files/..%2F..%2Fsecret").status_code in (400, 404)


def test_sync_patch_and_pull(admin, dataset):
    first = rows(admin, dataset["id"])["rows"][0]
    op = {"id": first["id"], "base_rev": first["rev"], "base": {"Von": None, "Bis": None},
          "patch": {"Von": 100, "Bis": 112.5, "Ist": 12.5}}
    out = admin.post(f"/api/datasets/{dataset['id']}/sync", json={"ops": [op]}).json()
    assert out["results"][0]["status"] == "ok"
    assert out["results"][0]["row"]["rev"] == first["rev"] + 1
    changes = rows(admin, dataset["id"], since=dataset["seq"])["rows"]
    assert [r["id"] for r in changes] == [first["id"]]
    assert changes[0]["data"]["Ist"] == 12.5


def test_sync_field_level_conflict(admin, dataset):
    first = rows(admin, dataset["id"])["rows"][0]
    url = f"/api/datasets/{dataset['id']}/sync"
    # Client A setzt "Von", Client B (alte Revision) setzt "Von" abweichend und zusätzlich "Datum"
    admin.post(url, json={"ops": [{"id": first["id"], "base_rev": first["rev"], "base": {"Von": None}, "patch": {"Von": 5}}]})
    stale = {"id": first["id"], "base_rev": first["rev"], "base": {"Von": None, "Datum": None},
             "patch": {"Von": 99, "Datum": "21.10.26"}}
    result = admin.post(url, json={"ops": [stale]}).json()["results"][0]
    assert result["status"] == "conflict" and result["conflicts"] == ["Von"]
    assert result["row"]["data"]["Von"] == 5  # fremde Änderung bleibt
    assert result["row"]["data"]["Datum"] == "21.10.26"  # nicht kollidierendes Feld wird übernommen


def test_sync_same_value_is_not_conflict(admin, dataset):
    first = rows(admin, dataset["id"])["rows"][0]
    url = f"/api/datasets/{dataset['id']}/sync"
    op = {"id": first["id"], "base_rev": first["rev"], "base": {"Von": None}, "patch": {"Von": 5}}
    admin.post(url, json={"ops": [op]})
    assert admin.post(url, json={"ops": [op]}).json()["results"][0]["status"] == "ok"


def test_sync_create_delete_and_unknown_column(admin, dataset):
    url = f"/api/datasets/{dataset['id']}/sync"
    out = admin.post(url, json={"ops": [
        {"client_id": "c1", "patch": {"Kabel": "NEU", "Länge": 7}},
        {"client_id": "c2", "patch": {"Gibtsnicht": 1}},
    ]}).json()
    assert out["results"][0]["status"] == "ok" and out["results"][0]["client_id"] == "c1"
    assert out["results"][1]["status"] == "error"
    new_id = out["results"][0]["id"]
    admin.post(url, json={"ops": [{"id": new_id, "delete": True}]})
    assert new_id not in [r["id"] for r in rows(admin, dataset["id"])["rows"]]
    tomb = rows(admin, dataset["id"], since=dataset["seq"])["rows"]
    assert any(r["id"] == new_id and r["deleted"] for r in tomb)


def test_analysis_and_export(admin, dataset):
    url = f"/api/datasets/{dataset['id']}"
    assert admin.get(f"{url}/analysis").status_code == 409
    admin.patch(url, json={"settings": {"mapping": MAPPING, "ignore_short": True, "min_length": 5}})
    first = rows(admin, dataset["id"])["rows"][0]
    admin.post(f"{url}/sync", json={"ops": [{"id": first["id"], "base_rev": first["rev"], "patch": {"Ist": 10}}]})
    result = admin.get(f"{url}/analysis").json()
    assert result["ignored"] == 1
    assert result["total"]["total"] == 3 and result["total"]["done"] == 1
    assert [g["label"] for g in result["groups"]] == ["3x1,5", "5x2,5"]

    exported = pd.read_excel(io.BytesIO(admin.get(f"{url}/export").content))
    assert len(exported) == 4 and exported.loc[0, "Ist"] == 10


def test_add_columns(admin, dataset):
    r = admin.patch(f"/api/datasets/{dataset['id']}", json={"add_columns": ["Notiz", "Kabel"]})
    assert r.json()["columns"][-1] == "Notiz" and r.json()["columns"].count("Kabel") == 1


def test_project_permissions(admin, dataset):
    bob = make_user(admin)
    assert bob.get(f"/api/datasets/{dataset['id']}").status_code == 404  # kein Mitglied: Projekt bleibt unsichtbar
    assert bob.get("/api/projects").json() == []
    assert bob.get("/api/admin/users").status_code == 403

    pid = dataset["project_id"]
    admin.put(f"/api/projects/{pid}/members", json={"username": "bob", "role": "viewer"})
    assert bob.get(f"/api/datasets/{dataset['id']}").status_code == 200
    r = bob.post(f"/api/datasets/{dataset['id']}/sync", json={"ops": []})
    assert r.status_code == 403
    admin.put(f"/api/projects/{pid}/members", json={"username": "bob", "role": "editor"})
    assert bob.post(f"/api/datasets/{dataset['id']}/sync", json={"ops": []}).status_code == 200
    assert bob.delete(f"/api/datasets/{dataset['id']}").status_code == 403


def test_last_owner_cannot_be_removed(admin, dataset):
    pid = dataset["project_id"]
    owner_id = admin.get(f"/api/projects/{pid}/members").json()[0]["user_id"]
    assert admin.delete(f"/api/projects/{pid}/members/{owner_id}").status_code == 400


def test_api_key_flow(admin, dataset):
    created = admin.post("/api/api-keys", json={"name": "Windows-App"}).json()
    assert created["key"].startswith("wtk_")
    plain = TestClient(app)
    assert plain.get("/api/projects", headers={"X-API-Key": created["key"]}).status_code == 200
    assert plain.get("/api/projects", headers={"Authorization": f"Bearer {created['key']}"}).status_code == 200
    assert plain.get("/api/projects", headers={"X-API-Key": "wtk_falsch"}).status_code == 401
    # Mit API-Key lassen sich keine weiteren Keys erzeugen
    assert plain.post("/api/api-keys", json={"name": "x"}, headers={"X-API-Key": created["key"]}).status_code == 403
    listed = admin.get("/api/api-keys").json()
    assert "key" not in listed[0] and listed[0]["last_used_at"]
    admin.delete(f"/api/api-keys/{created['id']}")
    assert plain.get("/api/projects", headers={"X-API-Key": created["key"]}).status_code == 401


def test_share_view_and_edit_links(admin, dataset):
    url = f"/api/datasets/{dataset['id']}/shares"
    view = admin.post(url, json={"label": "Kunde", "mode": "view", "hours": 2}).json()
    token = view["url"].rsplit("/s/", 1)[1]
    guest = TestClient(app)
    opened = guest.get(f"/api/share/{token}").json()
    assert opened["mode"] == "view" and len(opened["rows"]) == 4
    assert guest.post(f"/api/share/{token}/sync", json={"ops": []}).status_code == 403
    assert guest.get("/api/projects").status_code == 401

    edit = admin.post(url, json={"mode": "edit"}).json()
    etoken = edit["url"].rsplit("/s/", 1)[1]
    row = opened["rows"][0]
    ok = guest.post(f"/api/share/{etoken}/sync", json={"ops": [{"id": row["id"], "base_rev": row["rev"], "patch": {"Von": 1}}]})
    assert ok.json()["results"][0]["status"] == "ok"
    created = guest.post(f"/api/share/{etoken}/sync", json={"ops": [{"patch": {"Kabel": "X"}}]}).json()
    assert created["results"][0]["status"] == "error"  # Gäste dürfen keine Zeilen anlegen

    admin.delete(f"{url}/{view['id']}")
    assert guest.get(f"/api/share/{token}").status_code == 404
    assert guest.get("/api/share/unbekannt").status_code == 404


def test_expired_share_is_rejected(admin, dataset):
    from datetime import timedelta
    from wtserver.db import SessionLocal
    from wtserver.models import ShareLink, utcnow

    token = admin.post(f"/api/datasets/{dataset['id']}/shares", json={}).json()["url"].rsplit("/s/", 1)[1]
    with SessionLocal() as db:
        link = db.query(ShareLink).first()
        link.expires_at = utcnow() - timedelta(minutes=1)
        db.commit()
    assert TestClient(app).get(f"/api/share/{token}").status_code == 404


def test_audit_log_records_actions(admin, dataset):
    actions = {a["action"] for a in admin.get("/api/admin/audit").json()}
    assert {"login", "project_created", "file_uploaded", "dataset_imported"} <= actions


def test_change_password_and_inactive_user(admin):
    bob = make_user(admin)
    assert bob.post("/api/auth/password", json={"current_password": "bob-password-1", "new_password": "kurz"}).status_code == 400
    assert bob.post("/api/auth/password", json={"current_password": "bob-password-1", "new_password": "neues-passwort-2"}).status_code == 200
    uid = bob.get("/api/auth/me").json()["id"]
    admin.patch(f"/api/admin/users/{uid}", json={"is_active": False})
    assert bob.get("/api/auth/me").status_code == 401
    assert TestClient(app).post("/api/auth/login", json={"username": "bob", "password": "neues-passwort-2"}).status_code == 401


def test_security_headers(client):
    r = client.get("/api/health")
    assert r.headers["x-content-type-options"] == "nosniff"
    assert "frame-ancestors 'none'" in r.headers["content-security-policy"]
