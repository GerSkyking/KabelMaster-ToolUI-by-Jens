"""LDAP-/Active-Directory-Anmeldung: Dienstkonto sucht den Benutzer, anschließend Bind mit dessen Passwort."""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Callable

from ldap3 import ALL, SUBTREE, Connection, Server, Tls
from ldap3.core.exceptions import LDAPException
from ldap3.utils.conv import escape_filter_chars

from wtserver.config import Settings

log = logging.getLogger("wtserver.ldap")


@dataclass
class LdapIdentity:
    dn: str
    username: str
    email: str
    display_name: str
    is_admin: bool


ConnectionFactory = Callable[[Settings, str | None, str | None], Connection]


def _first(value: object) -> str:
    if isinstance(value, (list, tuple)):
        return str(value[0]) if value else ""
    return "" if value in (None, "[]") else str(value)


def default_connection(settings: Settings, user_dn: str | None, password: str | None) -> Connection:
    server = Server(settings.ldap_server_uri, get_info=ALL, tls=Tls() if settings.ldap_start_tls else None)
    connection = Connection(server, user=user_dn, password=password, raise_exceptions=False)
    if settings.ldap_start_tls:
        connection.start_tls()
    return connection


def authenticate(
    settings: Settings, username: str, password: str, connect: ConnectionFactory = default_connection
) -> LdapIdentity | None:
    """None bei falschen Zugangsdaten oder wenn der LDAP-Server nicht erreichbar ist."""
    if not settings.ldap_enabled or not username or not password:
        return None  # leeres Passwort würde bei vielen Servern als anonymer Bind "gelingen"
    try:
        search = connect(settings, settings.ldap_bind_dn or None, settings.ldap_bind_password or None)
        if not search.bind():
            log.error("LDAP-Dienstkonto konnte nicht binden: %s", search.result)
            return None
        wanted = [settings.ldap_attr_username, settings.ldap_attr_email, settings.ldap_attr_name, "memberOf"]
        search.search(
            settings.ldap_user_base,
            settings.ldap_user_filter.format(username=escape_filter_chars(username)),
            search_scope=SUBTREE,
            attributes=wanted,
            size_limit=2,
        )
        entries = list(search.entries)
        search.unbind()
        if len(entries) != 1:
            return None
        entry = entries[0]
        user_connection = connect(settings, entry.entry_dn, password)
        if not user_connection.bind():
            return None
        user_connection.unbind()
        attrs = entry.entry_attributes_as_dict
        groups = {str(g).lower() for g in attrs.get("memberOf", [])}
        return LdapIdentity(
            dn=entry.entry_dn,
            username=_first(attrs.get(settings.ldap_attr_username)) or username,
            email=_first(attrs.get(settings.ldap_attr_email)),
            display_name=_first(attrs.get(settings.ldap_attr_name)),
            is_admin=bool(settings.ldap_admin_group_dn) and settings.ldap_admin_group_dn.lower() in groups,
        )
    except LDAPException as exc:
        log.error("LDAP-Fehler: %s", exc)
        return None
