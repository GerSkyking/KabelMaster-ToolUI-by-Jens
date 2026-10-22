"""Konfiguration ausschließlich über Umgebungsvariablen (siehe .env.example)."""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

_DEFAULT_SECRET = "change-me-in-production"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    environment: str = "development"  # "production" erzwingt ein eigenes SECRET_KEY
    database_url: str = "sqlite:///./data/wt.db"
    data_dir: Path = Path("./data")
    secret_key: str = _DEFAULT_SECRET
    base_url: str = "http://localhost:8000"  # öffentliche URL (für OIDC-Callbacks und Share-Links)
    cookie_secure: bool = False
    session_hours: int = 12
    cors_origins: str = ""  # Komma-getrennt, nur für getrenntes Frontend (Dev)
    max_upload_mb: int = 50
    share_default_hours: int = 72
    static_dir: Path | None = None  # gebautes Frontend, wird vom Server mit ausgeliefert

    # Logging
    log_level: str = "INFO"
    log_json: bool = True
    log_to_file: bool = True

    # Sicherungen: täglich automatisch zur angegebenen Uhrzeit (Serverzeit), ältere werden gelöscht
    backup_enabled: bool = True
    backup_time: str = "02:00"  # HH:MM
    backup_keep: int = 14  # Anzahl automatischer Sicherungen
    backup_include_files: bool = False  # Excel-Dateien aus den Projektordnern mitsichern

    # Bootstrap-Admin (wird beim Start angelegt, falls noch kein Benutzer existiert)
    admin_username: str = "admin"
    admin_password: str = ""
    admin_email: str = ""

    # Anmeldearten (alle gleichzeitig nutzbar)
    local_login_enabled: bool = True
    auto_create_users: bool = True  # externe Benutzer beim ersten Login anlegen

    # OpenID Connect (Discovery über Issuer)
    oidc_issuer: str = ""
    oidc_client_id: str = ""
    oidc_client_secret: str = ""
    oidc_name: str = "OpenID Connect"
    oidc_scopes: str = "openid profile email"
    oidc_groups_claim: str = "groups"
    oidc_admin_group: str = ""

    # Generisches OAuth2 (z. B. GitHub, Gitea): Userinfo-Endpunkt liefert die Identität
    oauth2_name: str = "OAuth2"
    oauth2_authorize_url: str = ""
    oauth2_token_url: str = ""
    oauth2_userinfo_url: str = ""
    oauth2_client_id: str = ""
    oauth2_client_secret: str = ""
    oauth2_scopes: str = "read:user user:email"
    oauth2_id_field: str = "id"
    oauth2_username_field: str = "login"
    oauth2_email_field: str = "email"
    oauth2_name_field: str = "name"

    # LDAP / Active Directory
    ldap_server_uri: str = ""  # z. B. ldaps://ldap.example.org
    ldap_start_tls: bool = False
    ldap_bind_dn: str = ""  # Dienstkonto für die Benutzersuche
    ldap_bind_password: str = ""
    ldap_user_base: str = ""  # z. B. ou=people,dc=example,dc=org
    ldap_user_filter: str = "(uid={username})"  # AD: (sAMAccountName={username})
    ldap_attr_email: str = "mail"
    ldap_attr_name: str = "cn"
    ldap_attr_username: str = "uid"
    ldap_admin_group_dn: str = ""  # Mitglieder (memberOf) werden Administrator

    @property
    def oidc_enabled(self) -> bool:
        return bool(self.oidc_issuer and self.oidc_client_id)

    @property
    def oauth2_enabled(self) -> bool:
        return bool(self.oauth2_authorize_url and self.oauth2_token_url and self.oauth2_client_id)

    @property
    def ldap_enabled(self) -> bool:
        return bool(self.ldap_server_uri and self.ldap_user_base)

    @property
    def projects_dir(self) -> Path:
        return self.data_dir / "projects"

    @property
    def backups_dir(self) -> Path:
        return self.data_dir / "backups"

    @property
    def logs_dir(self) -> Path:
        return self.data_dir / "logs"

    @model_validator(mode="after")
    def _check_secret(self) -> "Settings":
        if self.environment == "production" and (self.secret_key == _DEFAULT_SECRET or len(self.secret_key) < 32):
            raise ValueError("SECRET_KEY muss in Produktion gesetzt sein (mindestens 32 Zeichen).")
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
