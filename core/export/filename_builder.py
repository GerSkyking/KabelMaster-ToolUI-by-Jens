"""Export-Dateinamen: Firma_YYYY-MM-DD_Originaldateiname, bei Stapelverarbeitung
zusätzlich der Suchbegriff: Firma_YYYY-MM-DD_Suchbegriff_Originaldateiname.

Leere/deaktivierte Segmente (z. B. Firma deaktiviert) werden ausgelassen,
damit keine doppelten Unterstriche entstehen.
"""
from __future__ import annotations

_INVALID_FILENAME_CHARS = '<>:"/\\|?*'


def _sanitize(text: str) -> str:
    cleaned = "".join(ch for ch in text if ch not in _INVALID_FILENAME_CHARS).strip()
    return cleaned or "Export"


class FilenameBuilder:
    @staticmethod
    def build_single(company: str | None, date: str | None, original_stem: str) -> str:
        parts = [_sanitize(p) for p in (company, date) if p]
        parts.append(_sanitize(original_stem))
        return "_".join(parts)

    @staticmethod
    def build_batch(company: str | None, date: str | None, search_term: str, original_stem: str) -> str:
        parts = [_sanitize(p) for p in (company, date, search_term) if p]
        parts.append(_sanitize(original_stem))
        return "_".join(parts)
