"""Globale Metadaten-Felder (Sidebar): Datum, Ersteller, Firma, Projekt/Funktion, Ort."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any


@dataclass
class GlobalField:
    """Ein einzelnes Sidebar-Feld: Wert + Aktivieren-Checkbox.

    Ist ``enabled`` False, bleibt ``value`` gespeichert, wird aber nicht in
    Exporte (Kopfzeile, Dateiname) übernommen.
    """

    value: str = ""
    enabled: bool = True

    def to_dict(self) -> dict[str, Any]:
        return {"value": self.value, "enabled": self.enabled}

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> "GlobalField":
        data = data or {}
        return cls(value=str(data.get("value", "")), enabled=bool(data.get("enabled", True)))


@dataclass
class GlobalSettings:
    date: GlobalField
    creator: GlobalField
    company: GlobalField
    project: GlobalField
    location: GlobalField

    @classmethod
    def create_default(cls) -> "GlobalSettings":
        return cls(
            date=GlobalField(value=date.today().isoformat(), enabled=True),
            creator=GlobalField(),
            company=GlobalField(),
            project=GlobalField(),
            location=GlobalField(),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "date": self.date.to_dict(),
            "creator": self.creator.to_dict(),
            "company": self.company.to_dict(),
            "project": self.project.to_dict(),
            "location": self.location.to_dict(),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> "GlobalSettings":
        data = data or {}
        defaults = cls.create_default()
        return cls(
            date=GlobalField.from_dict(data["date"]) if "date" in data else defaults.date,
            creator=GlobalField.from_dict(data.get("creator")),
            company=GlobalField.from_dict(data.get("company")),
            project=GlobalField.from_dict(data.get("project")),
            location=GlobalField.from_dict(data.get("location")),
        )
