"""Offline-Abgleich der Windows-App-Bibliothek gegen den echten Server (API-Key, Excel lokal bearbeiten)."""
import pandas as pd
import pytest
from fastapi.testclient import TestClient

from wtserver.main import app
from wtsync.client import SyncError, WtClient, snapshot_path


@pytest.fixture
def client_for(admin):
    key = admin.post("/api/api-keys", json={"name": "Windows"}).json()["key"]
    return lambda: WtClient(http=TestClient(app, headers={"X-API-Key": key}))


def test_pull_edit_offline_push(admin, dataset, client_for, tmp_path):
    client = client_for()
    path = tmp_path / "liste.xlsx"
    frame = client.pull(dataset["id"], path)
    assert len(frame) == 4 and snapshot_path(path).is_file()

    # offline in Excel bearbeiten: Werte setzen, neue Spalte, neue Zeile
    edited = pd.read_excel(path, dtype=object)
    edited.loc[0, ["Von", "Bis", "Ist", "Datum"]] = [100, 112.5, 12.5, "22.10.26"]
    edited["Notiz"] = None
    edited.loc[0, "Notiz"] = "geprüft"
    edited.loc[len(edited)] = {"Kabel": "W5", "Querschnitt": "3x1,5", "Länge": 3}
    edited.to_excel(path, index=False)

    report = client.push(path)
    assert report.changed_rows == 1 and report.created_rows == 1 and report.new_columns == ["Notiz"]
    assert not report.conflicts and not report.errors

    rows = admin.get(f"/api/datasets/{dataset['id']}/rows").json()["rows"]
    assert len(rows) == 5
    assert rows[0]["data"]["Ist"] == 12.5 and rows[0]["data"]["Notiz"] == "geprüft"
    assert rows[4]["data"]["Kabel"] == "W5"
    # nach dem Push ist die Datei auf Server-Stand: ein zweiter Push ändert nichts
    assert client.push(path).changed_rows == 0


def test_conflict_keeps_server_value(admin, dataset, client_for, tmp_path):
    client = client_for()
    path = tmp_path / "liste.xlsx"
    client.pull(dataset["id"], path)

    first = admin.get(f"/api/datasets/{dataset['id']}/rows").json()["rows"][0]
    admin.post(f"/api/datasets/{dataset['id']}/sync",
               json={"ops": [{"id": first["id"], "base_rev": first["rev"], "base": {"Von": None}, "patch": {"Von": 7}}]})

    edited = pd.read_excel(path, dtype=object)
    edited.loc[0, "Von"] = 55
    edited.loc[0, "Datum"] = "22.10.26"
    edited.to_excel(path, index=False)

    report = client.push(path)
    assert [c["field"] for c in report.conflicts] == ["Von"]
    final = admin.get(f"/api/datasets/{dataset['id']}/rows").json()["rows"][0]["data"]
    assert final["Von"] == 7 and final["Datum"] == "22.10.26"


def test_push_without_snapshot_and_bad_key(tmp_path, client_for):
    with pytest.raises(SyncError):
        client_for().push(tmp_path / "x.xlsx")
    bad = WtClient(http=TestClient(app, headers={"X-API-Key": "wtk_falsch"}))
    with pytest.raises(SyncError):
        bad.projects()
