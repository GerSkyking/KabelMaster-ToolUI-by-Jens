"""Testumgebung: SQLite im Temp-Verzeichnis, Konfiguration über Umgebungsvariablen vor dem Import."""
import os
import tempfile
from pathlib import Path

_tmp = Path(tempfile.mkdtemp(prefix="wt-test-"))
os.environ.update(
    DATABASE_URL=f"sqlite:///{(_tmp / 'test.db').as_posix()}",
    DATA_DIR=str(_tmp / "data"),
    SECRET_KEY="test-secret-key-test-secret-key-1234",
    ADMIN_USERNAME="admin",
    ADMIN_PASSWORD="admin-password-123",
    LOG_TO_FILE="false",
    LOG_JSON="false",
    BASE_URL="http://testserver",
)

import pandas as pd  # noqa: E402
import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from wtserver.db import Base, SessionLocal, engine  # noqa: E402
from wtserver.main import app  # noqa: E402
from wtserver.accounts import ensure_bootstrap_admin  # noqa: E402
from wtserver.config import get_settings  # noqa: E402
from wtserver.security import throttle  # noqa: E402


@pytest.fixture(autouse=True)
def fresh_db():
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    throttle._failures.clear()
    with SessionLocal() as db:
        ensure_bootstrap_admin(db, get_settings())
    yield


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)


@pytest.fixture
def admin(client: TestClient) -> TestClient:
    response = client.post("/api/auth/login", json={"username": "admin", "password": "admin-password-123"})
    assert response.status_code == 200, response.text
    return client


@pytest.fixture
def cable_xlsx(tmp_path) -> Path:
    path = tmp_path / "Kabelliste.xlsx"
    pd.DataFrame(
        {
            "Kabel": ["W1", "W2", "W3", "W4"],
            "Querschnitt": ["3x1,5", "3x1,5", "5x2,5", "5x2,5"],
            "Länge": [10, 1, 20, 30],
            "Von": [None] * 4,
            "Bis": [None] * 4,
            "Ist": [None] * 4,
            "Datum": [None] * 4,
        }
    ).to_excel(path, index=False)
    return path


@pytest.fixture
def dataset(admin: TestClient, cable_xlsx: Path) -> dict:
    """Projekt mit importiertem Kabel-Datensatz (als Admin)."""
    project = admin.post("/api/projects", json={"name": "Anlage Nord"}).json()
    with cable_xlsx.open("rb") as handle:
        up = admin.post(f"/api/projects/{project['id']}/files", files={"file": (cable_xlsx.name, handle)})
    assert up.status_code == 201, up.text
    created = admin.post(f"/api/projects/{project['id']}/datasets", json={"file": cable_xlsx.name})
    assert created.status_code == 201, created.text
    return created.json()
