"""Kommandozeile:  python -m wtsync pull|push|list ...   (URL und Key per Argument oder WT_URL / WT_API_KEY)"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from wtsync.client import SyncError, WtClient


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="wtsync", description="UW Kabel-Master - Offline-Abgleich per API-Key")
    parser.add_argument("--url", default=os.environ.get("WT_URL", ""), help="Server-URL, z. B. https://listen.example.org")
    parser.add_argument("--key", default=os.environ.get("WT_API_KEY", ""), help="API-Key (wtk_...)")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("list", help="Projekte und Listen anzeigen")
    pull = sub.add_parser("pull", help="Liste als Excel-Datei herunterladen")
    pull.add_argument("dataset", type=int)
    pull.add_argument("file", type=Path)
    push = sub.add_parser("push", help="Lokale Änderungen einer mit pull erzeugten Datei übertragen")
    push.add_argument("file", type=Path)
    args = parser.parse_args(argv)

    if not args.url or not args.key:
        parser.error("URL und API-Key werden benötigt (--url/--key oder WT_URL/WT_API_KEY).")
    client = WtClient(args.url, args.key)
    try:
        if args.command == "list":
            for project in client.projects():
                print(f"[{project['id']}] {project['name']}")
                for dataset in project["datasets"]:
                    print(f"    Liste {dataset['id']}: {dataset['name']}")
        elif args.command == "pull":
            frame = client.pull(args.dataset, args.file)
            print(f"{len(frame)} Zeilen nach {args.file} geladen.")
        else:
            report = client.push(args.file)
            print(f"{report.changed_rows} Zeilen geändert, {report.created_rows} neu, "
                  f"{len(report.new_columns)} neue Spalten.")
            for conflict in report.conflicts:
                print(f"KONFLIKT Zeile-ID {conflict['row']}, Feld '{conflict['field']}': "
                      f"lokal {conflict['mine']!r}, Server {conflict['theirs']!r} (Server-Wert behalten)")
            for error in report.errors:
                print(f"FEHLER: {error}")
            if report.missing_rows:
                print(f"Hinweis: {report.missing_rows} Zeile(n) fehlen lokal - am Server nicht gelöscht.")
            return 1 if report.conflicts or report.errors else 0
    except SyncError as exc:
        print(f"Fehler: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
