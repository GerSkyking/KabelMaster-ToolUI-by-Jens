"""LDAP-Login gegen einen simulierten Server (ldap3 MOCK_SYNC)."""
from ldap3 import MOCK_SYNC, OFFLINE_AD_2012_R2, Connection, Server
from fastapi.testclient import TestClient

from wtserver import ldap_auth
from wtserver.config import get_settings
from wtserver.main import app

USER_DN = "cn=alice,ou=people,dc=example,dc=org"
SERVICE_DN = "cn=svc,dc=example,dc=org"
ADMIN_GROUP = "cn=wt-admins,ou=groups,dc=example,dc=org"


def mock_factory(members: list[str]):
    server = Server("fake", get_info=OFFLINE_AD_2012_R2)

    def connect(settings, user_dn, password):
        connection = Connection(server, user=user_dn, password=password, client_strategy=MOCK_SYNC)
        for dn, pw, attrs in (
            (SERVICE_DN, "svc-pw", {}),
            (USER_DN, "alice-pw", {"uid": "alice", "mail": "alice@example.org", "cn": "Alice A.", "memberOf": members}),
        ):
            connection.strategy.add_entry(dn, {"userPassword": pw, "objectClass": "inetOrgPerson", **attrs})
        return connection

    return connect


def ldap_settings(**extra):
    return get_settings().model_copy(update={
        "ldap_server_uri": "ldap://fake", "ldap_user_base": "ou=people,dc=example,dc=org",
        "ldap_bind_dn": SERVICE_DN, "ldap_bind_password": "svc-pw", "ldap_admin_group_dn": ADMIN_GROUP, **extra,
    })


def test_ldap_success_and_admin_group():
    identity = ldap_auth.authenticate(ldap_settings(), "alice", "alice-pw", mock_factory([ADMIN_GROUP]))
    assert identity and identity.email == "alice@example.org" and identity.is_admin
    plain = ldap_auth.authenticate(ldap_settings(), "alice", "alice-pw", mock_factory([]))
    assert plain and not plain.is_admin


def test_ldap_rejects_wrong_empty_and_unknown():
    factory = mock_factory([])
    assert ldap_auth.authenticate(ldap_settings(), "alice", "falsch", factory) is None
    assert ldap_auth.authenticate(ldap_settings(), "alice", "", factory) is None
    assert ldap_auth.authenticate(ldap_settings(), "niemand", "x", factory) is None


def test_ldap_filter_injection_is_escaped():
    assert ldap_auth.authenticate(ldap_settings(), "*)(uid=*", "alice-pw", mock_factory([])) is None


def test_ldap_login_provisions_user(monkeypatch):
    settings = ldap_settings()
    original = ldap_auth.authenticate
    monkeypatch.setattr(ldap_auth, "authenticate",
                        lambda s, u, p: original(settings, u, p, mock_factory([ADMIN_GROUP])))
    monkeypatch.setattr(get_settings(), "ldap_server_uri", "ldap://fake")
    monkeypatch.setattr(get_settings(), "ldap_user_base", "ou=people,dc=example,dc=org")
    monkeypatch.setattr(get_settings(), "ldap_admin_group_dn", ADMIN_GROUP)
    client = TestClient(app)
    assert client.get("/api/auth/config").json()["ldap"] is True
    response = client.post("/api/auth/login", json={"username": "alice", "password": "alice-pw"})
    assert response.status_code == 200
    assert response.json()["provider"] == "ldap" and response.json()["role"] == "admin"
    assert client.post("/api/auth/login", json={"username": "alice", "password": "falsch"}).status_code == 401
