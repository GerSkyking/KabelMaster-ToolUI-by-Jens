"""Minimaler iCalendar-Leser (ICS-Links von Nextcloud, Google, Outlook ...) und sicherer Abruf.

Unterstützt VEVENT mit DTSTART/DTEND (Datum oder Datum-Zeit), SUMMARY und einfache Wiederholungen
(RRULE: DAILY/WEEKLY/MONTHLY/YEARLY mit INTERVAL, COUNT, UNTIL, BYDAY bei WEEKLY; EXDATE). Komplexere Regeln
(BYSETPOS, Ausnahme-Instanzen mit RECURRENCE-ID ...) werden bewusst nicht ausgewertet."""
from __future__ import annotations

import ipaddress
import re
import socket
import urllib.error
import urllib.request
from datetime import date, datetime, timedelta
from urllib.parse import urlsplit

MAX_BYTES = 5 * 1024 * 1024
MAX_OCCURRENCES = 800
_WEEKDAYS = ["MO", "TU", "WE", "TH", "FR", "SA", "SU"]


class FeedError(Exception):
    """Kalender nicht abrufbar oder ungültig (Text ist für Benutzer gedacht)."""


def _blocked(address: str) -> bool:
    ip = ipaddress.ip_address(address)
    return ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_multicast or ip.is_reserved or ip.is_unspecified


def check_url(url: str, allow_private: bool) -> str:
    """Nur http(s); ohne ``allow_private`` keine Ziele im internen Netz (Schutz vor Zugriffen auf Interna des Servers)."""
    if url.lower().startswith("webcal://"):
        url = "https://" + url[9:]
    parts = urlsplit(url)
    if parts.scheme not in ("http", "https") or not parts.hostname:
        raise FeedError("Nur http(s)- oder webcal-Adressen sind erlaubt.")
    if not allow_private:
        try:
            infos = socket.getaddrinfo(parts.hostname, parts.port or (443 if parts.scheme == "https" else 80))
        except OSError:
            raise FeedError("Adresse nicht auflösbar.") from None
        if any(_blocked(info[4][0]) for info in infos):
            raise FeedError("Adressen im internen Netz sind nicht erlaubt (Einstellung CALENDAR_ALLOW_PRIVATE).")
    return url


def fetch(url: str, allow_private: bool = False, timeout: float = 8.0) -> str:
    class Redirects(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, req, fp, code, msg, headers, newurl):
            check_url(newurl, allow_private)  # auch Weiterleitungen prüfen
            return super().redirect_request(req, fp, code, msg, headers, newurl)

    url = check_url(url, allow_private)
    opener = urllib.request.build_opener(Redirects)
    try:
        with opener.open(urllib.request.Request(url, headers={"User-Agent": "KabelMaster-Kalender"}), timeout=timeout) as resp:
            data = resp.read(MAX_BYTES + 1)
    except FeedError:
        raise
    except urllib.error.HTTPError as e:
        raise FeedError(f"Server antwortet mit Fehler {e.code}.") from None
    except (urllib.error.URLError, OSError, ValueError) as e:
        raise FeedError(f"Abruf fehlgeschlagen: {getattr(e, 'reason', e)}") from None
    if len(data) > MAX_BYTES:
        raise FeedError("Kalenderdatei größer als 5 MB.")
    text = data.decode("utf-8", errors="replace")
    if "BEGIN:VCALENDAR" not in text:
        raise FeedError("Das ist keine iCal-Datei (BEGIN:VCALENDAR fehlt).")
    return text


def _unfold(text: str) -> list[str]:
    lines: list[str] = []
    for line in text.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        if line[:1] in (" ", "\t") and lines:
            lines[-1] += line[1:]
        else:
            lines.append(line)
    return lines


def _unescape(value: str) -> str:
    return re.sub(r"\\([,;nN\\])", lambda m: "\n" if m.group(1) in "nN" else m.group(1), value)


def _parse_date(value: str) -> tuple[date, str] | None:
    """-> (Datum, Uhrzeit HH:MM oder ''). Zeitzonen werden nicht umgerechnet (Anzeige in der Zeit des Kalenders)."""
    m = re.match(r"^(\d{4})(\d{2})(\d{2})(?:T(\d{2})(\d{2}))?", value.strip())
    if not m:
        return None
    try:
        day = date(int(m[1]), int(m[2]), int(m[3]))
    except ValueError:
        return None
    return day, (f"{m[4]}:{m[5]}" if m[4] else "")


def _prop(line: str) -> tuple[str, dict[str, str], str]:
    head, _, value = line.partition(":")
    name, *params = head.split(";")
    return name.upper(), {k.upper(): v for k, _, v in (p.partition("=") for p in params)}, value


def _expand(start: date, rule: dict[str, str], exdates: set[date], lo: date, hi: date) -> list[date]:
    freq = rule.get("FREQ", "")
    if freq not in ("DAILY", "WEEKLY", "MONTHLY", "YEARLY"):
        return [start]
    interval = max(1, int(rule.get("INTERVAL", "1") or 1))
    count = int(rule["COUNT"]) if rule.get("COUNT", "").isdigit() else None
    until = (_parse_date(rule["UNTIL"]) or (None,))[0] if "UNTIL" in rule else None
    days = [d[-2:] for d in rule.get("BYDAY", "").split(",") if d[-2:] in _WEEKDAYS]
    out: list[date] = []
    produced = 0
    for step in range(0, 20000):
        if freq == "WEEKLY" and days:
            monday = start - timedelta(days=start.weekday()) + timedelta(weeks=step * interval)
            candidates = [c for c in sorted(monday + timedelta(days=_WEEKDAYS.index(d)) for d in days) if c >= start]
        else:
            candidates = [_nth(start, freq, step * interval)]
        if candidates and candidates[0] is not None and candidates[0] > hi:
            break
        for c in candidates:
            if c is None or (until is not None and c > until):
                continue
            produced += 1
            if count is not None and produced > count:
                return out
            if lo <= c <= hi and c not in exdates:
                out.append(c)
        if until is not None and candidates and candidates[-1] is not None and candidates[-1] > until:
            break
        if len(out) >= MAX_OCCURRENCES:
            break
    return out


def _nth(start: date, freq: str, n: int) -> date | None:
    """n-te Wiederholung (n Einheiten nach dem Start); None, wenn das Datum nicht existiert (z. B. 31. im Februar)."""
    if freq == "DAILY":
        return start + timedelta(days=n)
    if freq == "WEEKLY":
        return start + timedelta(weeks=n)
    try:
        if freq == "MONTHLY":
            month = start.month - 1 + n
            return start.replace(year=start.year + month // 12, month=month % 12 + 1)
        return start.replace(year=start.year + n)
    except ValueError:
        return None


def parse(text: str, lo: date, hi: date) -> list[dict]:
    """Termine im Zeitraum [lo, hi] als {title, start, end, time, all_day}; Datumsangaben JJJJ-MM-TT, Ende einschließlich."""
    events: list[dict] = []
    block: list[str] | None = None
    for line in _unfold(text):
        if line.upper() == "BEGIN:VEVENT":
            block = []
        elif line.upper() == "END:VEVENT" and block is not None:
            events.extend(_event(block, lo, hi))
            block = None
        elif block is not None:
            block.append(line)
    events.sort(key=lambda e: (e["start"], e["time"], e["title"]))
    return events[:5000]


def _event(lines: list[str], lo: date, hi: date) -> list[dict]:
    title, start, end, rrule, exdates, status, recurrence_id = "", None, None, "", set(), "", False
    for line in lines:
        name, params, value = _prop(line)
        if name == "SUMMARY":
            title = _unescape(value).strip()
        elif name == "DTSTART":
            start = _parse_date(value)
            all_day = params.get("VALUE") == "DATE" or len(value.strip()) == 8
        elif name == "DTEND":
            end = _parse_date(value)
        elif name == "RRULE":
            rrule = value
        elif name == "EXDATE":
            exdates |= {p[0] for p in (_parse_date(v) for v in value.split(",")) if p}
        elif name == "STATUS":
            status = value.upper()
        elif name == "RECURRENCE-ID":
            recurrence_id = True
    if start is None or status == "CANCELLED":
        return []
    first, time = start
    last = first
    if end is not None:
        last = end[0] - timedelta(days=1) if all_day and end[0] > first else end[0]
        last = max(first, last)
    span = last - first
    rule = dict(p.split("=", 1) for p in rrule.split(";") if "=" in p) if rrule and not recurrence_id else {}
    starts = _expand(first, rule, exdates, lo - span, hi) if rule else ([first] if lo - span <= first <= hi else [])
    return [{"title": title or "(ohne Titel)", "start": s.isoformat(), "end": (s + span).isoformat(), "time": time,
             "all_day": all_day} for s in starts[:MAX_OCCURRENCES]]
