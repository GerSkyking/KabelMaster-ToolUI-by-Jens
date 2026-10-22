"""KMK-PDF-Generator: rendert Beschrifter-Gruppen als Gitter-Layout auf DIN A4.

Layout-Logik:
- Seitenformat wird automatisch gewählt (Hoch-/Querformat) je nachdem,
  welches Format mehr Beschrifter pro Seite erlaubt (Kapazitätsvergleich).
- Beschrifter werden zeilenweise von links nach rechts, dann von oben
  nach unten auf die Seite gepackt.
- Gruppenüberschrift-Modus (config.header_mode):
    "own_row"     – volle Zeile mit grauem Hintergrund (klassisch)
    "first_field" – Überschrift als normaler Beschrifter (kein Platzverlust)
    "hidden"      – keine Überschrift
- Nahtlose Anordnung (config.seamless=True): Gruppen werden ohne künstlichen
  Zeilenbruch direkt hintereinander eingefügt. RESTE beginnt im nächsten freien Feld.
- Überlauf wird erkannt und mit rotem Rahmen markiert.
"""
from __future__ import annotations

from pathlib import Path

from reportlab.lib.colors import HexColor, black, lightgrey, white
from reportlab.lib.pagesizes import A4, landscape as rl_landscape
from reportlab.lib.units import mm
from reportlab.pdfbase.pdfmetrics import stringWidth
from reportlab.pdfgen.canvas import Canvas

from core.models.kmk_models import KmkConfig, KmkGroup

_FONT = "Helvetica"
_FONT_BOLD = "Helvetica-Bold"
_MARGIN_MM = 10.0
_CAP_HEIGHT_RATIO = 0.72  # Näherung für Helvetica: Versalhöhe / Schriftgröße
_LEADING_RATIO = 1.2       # Zeilenabstand-Faktor
_SHRINK_STEP_PT = 0.25     # Schrittweite bei der automatischen Verkleinerung


def _display_text(value: str) -> str:
    """Text für das PDF: ein führendes "'" vor "=" wird entfernt (Excel behält es)."""
    return value[1:] if value.startswith("'=") else value


class KmkPdfGenerator:
    """Erzeugt eine PDF-Datei mit KMK-Beschriftern im Gitterlayout."""

    def generate(
        self,
        groups: list[KmkGroup],
        config: KmkConfig,
        target_path: Path,
    ) -> list[str]:
        """Generiert die PDF-Datei und gibt Überlauf-Warnmeldungen zurück."""
        target_path.parent.mkdir(parents=True, exist_ok=True)

        label_w = config.kmk_type.width_pt
        label_h = config.kmk_type.height_pt
        margin = _MARGIN_MM * mm

        # Automatische Seitenausrichtung: die Variante mit mehr Beschriftern pro Seite gewinnt
        portrait_w, portrait_h = A4
        landscape_w, landscape_h = rl_landscape(A4)

        portrait_cols = max(1, int((portrait_w - 2 * margin) / label_w))
        portrait_rows = max(1, int((portrait_h - 2 * margin) / label_h))
        landscape_cols = max(1, int((landscape_w - 2 * margin) / label_w))
        landscape_rows = max(1, int((landscape_h - 2 * margin) / label_h))

        use_landscape = (landscape_cols * landscape_rows) > (portrait_cols * portrait_rows)
        page_size = rl_landscape(A4) if use_landscape else A4
        page_w, page_h = page_size
        labels_per_row = landscape_cols if use_landscape else portrait_cols
        labels_per_col = landscape_rows if use_landscape else portrait_rows

        c = Canvas(str(target_path), pagesize=page_size)
        col = 0
        row = 0
        warnings: list[str] = []
        # Rahmen werden erst nach allen Füllungen/Texten der Seite gezeichnet, damit die
        # weiße Füllung der Nachbarzelle sie nicht teilweise überdeckt (Strich-Lücken-Muster).
        frames: list[tuple[float, float, float, float, object, float]] = []

        # ---- Hilfsfunktionen ----

        def _flush_frames() -> None:
            c.setLineCap(2)   # projizierende Enden → saubere Ecken
            c.setLineJoin(0)
            for fx, fy, fw, fh, color, width in frames:
                c.setStrokeColor(color)
                c.setLineWidth(width)
                c.rect(fx, fy, fw, fh, stroke=1, fill=0)
            frames.clear()

        def _check_new_page() -> None:
            nonlocal col, row
            if row >= labels_per_col:
                _flush_frames()
                c.showPage()
                row = 0

        def _complete_row() -> None:
            """Füllt die aktuelle Zeile auf und wechselt zur nächsten."""
            nonlocal col, row
            if col > 0:
                col = 0
                row += 1
                _check_new_page()

        def _label_rect(r: int, cl: int) -> tuple[float, float]:
            """Gibt (x, y_bottom) eines Beschrifters an Position (col, row) zurück."""
            x = margin + cl * label_w
            y = page_h - margin - (r + 1) * label_h
            return x, y

        def _fit_font_size(
            lines: list[str], font: str, font_size: float, cell_h: float
        ) -> tuple[float, bool]:
            """Ermittelt die Schriftgröße, mit der der Text in die Zelle passt.

            Ohne auto_shrink bleibt font_size. Mit auto_shrink wird schrittweise bis
            min_font_size_pt verkleinert. Gibt (Schriftgröße, Überlauf) zurück.
            """
            padding = config.frame_padding_pt if config.frame_enabled else 2.0
            avail_w = label_w - 2 * padding
            avail_h = cell_h - 2 * padding

            def overflows(size: float) -> bool:
                leading = size * _LEADING_RATIO
                cap_h = size * _CAP_HEIGHT_RATIO
                block_h = (len(lines) - 1) * leading + cap_h
                return block_h > avail_h or any(
                    stringWidth(line, font, size) > avail_w for line in lines
                )

            size = font_size
            if config.auto_shrink:
                min_size = min(config.min_font_size_pt, font_size)
                while size > min_size and overflows(size):
                    size = max(min_size, size - _SHRINK_STEP_PT)
            return size, overflows(size)

        def _draw_centered_text(
            cx: float,
            cell_bottom: float,
            cell_h: float,
            lines: list[str],
            font: str,
            font_size: float,
        ) -> bool:
            """Zeichnet mehrzeiligen Text mittig in einer Zelle. Gibt True zurück wenn Überlauf."""
            if not lines:
                return False
            font_size, overflow = _fit_font_size(lines, font, font_size, cell_h)
            leading = font_size * _LEADING_RATIO
            cap_h = font_size * _CAP_HEIGHT_RATIO
            total_block_h = (len(lines) - 1) * leading + cap_h
            cell_center_y = cell_bottom + cell_h / 2
            y_first = cell_center_y + total_block_h / 2 - cap_h
            c.setFont(font, font_size)
            c.setFillColor(black)
            for i, line in enumerate(lines):
                c.drawCentredString(cx, y_first - i * leading, line)
            return overflow

        def _place_label(lines: list[str], is_header_label: bool = False) -> bool:
            """Zeichnet Beschrifter an aktueller Position, rückt Cursor vor.

            Gibt True zurück wenn Textüberlauf (nur für normale Beschrifter relevant).
            """
            nonlocal col, row
            lx, ly = _label_rect(row, col)

            if is_header_label:
                c.setFillColor(lightgrey)
                c.rect(lx, ly, label_w, label_h, stroke=0, fill=1)
                frames.append((lx, ly, label_w, label_h, black, 0.8))
            else:
                c.setFillColor(white)
                c.rect(lx, ly, label_w, label_h, stroke=0, fill=1)
                if config.frame_enabled:
                    frames.append((
                        lx, ly, label_w, label_h,
                        HexColor(config.frame_color), config.frame_width_pt,
                    ))

            content = [_display_text(ln) for ln in lines if ln.strip()]
            font = _FONT_BOLD if is_header_label else _FONT
            overflow = _draw_centered_text(
                lx + label_w / 2, ly, label_h, content, font, config.font_size_pt
            )
            if overflow and not is_header_label:
                frames.append((lx, ly, label_w, label_h, HexColor("#FF0000"), 1.0))

            col += 1
            if col >= labels_per_row:
                col = 0
                row += 1
                _check_new_page()
            return overflow and not is_header_label

        def _draw_full_header(title: str) -> None:
            """Zeichnet eine volle Überschriftszeile (gesamte Seitenbreite, grauer Hintergrund)."""
            hx = margin
            hy = page_h - margin - (row + 1) * label_h
            hw = labels_per_row * label_w
            c.setFillColor(lightgrey)
            c.rect(hx, hy, hw, label_h, stroke=0, fill=1)
            frames.append((hx, hy, hw, label_h, black, 1.0))
            _draw_centered_text(
                hx + hw / 2, hy, label_h,
                [f"<< {title} >>"], _FONT_BOLD, config.font_size_pt + 1,
            )

        # ---- Gruppen rendern ----

        seamless = config.seamless
        header_mode = config.header_mode

        for group in groups:
            # Zeilenumbruch vor der Gruppe wenn nötig:
            # - "own_row" benötigt immer volle Zeilenbreite → Zeile abschließen
            # - nicht-nahtlos → künstlicher Zeilenumbruch zwischen Gruppen
            if header_mode == "own_row" or not seamless:
                _complete_row()
                _check_new_page()

            # Gruppenüberschrift mit Kabelanzahl (nach Duplikat-Deckel = tatsächlich gedruckt)
            title = f"{group.title} ({len(group.labels)} Kabel)"
            if header_mode == "own_row":
                _draw_full_header(title)
                col = 0
                row += 1
                _check_new_page()
            elif header_mode == "first_field":
                # Überschrift als normaler Beschrifter (hervorgehoben, kein Extrazeilenverbrauch)
                _place_label([f"<< {title} >>"], is_header_label=True)
            # "hidden": keine Überschrift

            # Beschrifter der Gruppe
            for label in group.labels:
                content_lines = [ln for ln in label.lines if ln.strip()]
                overflow = _place_label(content_lines)
                if overflow:
                    label.overflow = True
                    preview = " / ".join(content_lines[:2])
                    warnings.append(
                        f"⚠ Beschrifter '{preview}' passt nicht in {config.kmk_type.name}"
                    )

        _flush_frames()
        c.save()
        return warnings
