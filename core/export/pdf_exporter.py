"""PDF-Export: schreibt ein ExportPayload als PDF, Layout möglichst nah am Excel-Export.

* Kopfzeile (links/mitte/rechts) und Tabellenspaltenköpfe werden auf jeder Seite wiederholt.
* Bei zu langem Zellinhalt wird die Schriftgröße dieser einzelnen Zelle automatisch
  verkleinert (bis zu einer Mindestgröße), siehe DESIGN.md Abschnitt 6.4.
"""
from __future__ import annotations

from pathlib import Path
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import ParagraphStyle
from reportlab.pdfbase.pdfmetrics import stringWidth
from reportlab.pdfgen import canvas as _rl_canvas
from reportlab.platypus import (
    BaseDocTemplate,
    Frame,
    NextPageTemplate,
    PageBreak,
    PageTemplate,
    Paragraph,
    SimpleDocTemplate,
    Table,
    TableStyle,
)

from core.export.units import px_to_points
from core.models.export_header_config import ExportHeaderConfig
from core.models.export_payload import ExportPayload

FONT_NAME = "Helvetica"
FONT_NAME_BOLD = "Helvetica-Bold"
CELL_PADDING_PT = 4
ALTERNATE_ROW_COLOR = colors.HexColor("#F0F0F0")
HEADER_AREA_PT = 40
MARGIN_PT = 24
FOOTER_AREA_PT = 20


class _NumberedCanvas(_rl_canvas.Canvas):
    """Zeichnet 'Seite X / Y' unten mittig auf jeder Seite (Zwei-Phasen-Render)."""

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._saved_page_states: list[dict] = []

    def showPage(self) -> None:
        self._saved_page_states.append(dict(self.__dict__))
        self._startPage()

    def save(self) -> None:
        num_pages = len(self._saved_page_states)
        for page_num, state in enumerate(self._saved_page_states, start=1):
            self.__dict__.update(state)
            self._draw_page_number(page_num, num_pages)
            _rl_canvas.Canvas.showPage(self)
        _rl_canvas.Canvas.save(self)

    def _draw_page_number(self, page_num: int, total_pages: int) -> None:
        self.saveState()
        self.setFont(FONT_NAME, 8)
        page_width = self._pagesize[0]
        self.drawCentredString(
            page_width / 2,
            MARGIN_PT / 2,
            f"Seite {page_num} / {total_pages}",
        )
        self.restoreState()


class PdfExporter:
    def export(self, payload: ExportPayload, target_path: Path) -> None:
        target_path.parent.mkdir(parents=True, exist_ok=True)

        col_widths_pt = [max(px_to_points(column.width_px), 1.0) for column in payload.columns]
        page_size = landscape(A4) if payload.landscape else A4

        document = SimpleDocTemplate(
            str(target_path),
            pagesize=page_size,
            leftMargin=MARGIN_PT,
            rightMargin=MARGIN_PT,
            topMargin=MARGIN_PT + HEADER_AREA_PT,
            bottomMargin=MARGIN_PT + FOOTER_AREA_PT,
        )

        table_data = self._build_table_data(payload, col_widths_pt)
        row_heights = self._build_row_heights(payload)
        table = Table(table_data, colWidths=col_widths_pt, rowHeights=row_heights, repeatRows=1)
        table.setStyle(self._build_table_style(payload))

        def draw_header(canvas, doc) -> None:
            self._draw_header(canvas, doc, payload.header)

        document.build(
            [table],
            onFirstPage=draw_header,
            onLaterPages=draw_header,
            canvasmaker=_NumberedCanvas,
        )

    def export_many(self, payloads: list[ExportPayload], target_path: Path) -> None:
        """Schreibt alle Payloads in ein PDF; jeder Payload beginnt auf einer neuen Seite.

        Kopfzeile je Payload eigenständig, Seitenformat und Seitennummer gelten für das ganze Dokument.
        """
        if not payloads:
            raise ValueError("Keine Daten zum Exportieren.")
        target_path.parent.mkdir(parents=True, exist_ok=True)
        page_size = landscape(A4) if payloads[0].landscape else A4
        page_w, page_h = page_size

        document = BaseDocTemplate(
            str(target_path),
            pagesize=page_size,
            leftMargin=MARGIN_PT,
            rightMargin=MARGIN_PT,
            topMargin=MARGIN_PT + HEADER_AREA_PT,
            bottomMargin=MARGIN_PT + FOOTER_AREA_PT,
        )
        frame = Frame(
            document.leftMargin,
            document.bottomMargin,
            page_w - document.leftMargin - document.rightMargin,
            page_h - document.topMargin - document.bottomMargin,
            id="normal",
        )

        story: list = []
        templates: list[PageTemplate] = []
        for index, payload in enumerate(payloads):
            def draw_header(canvas, doc, header=payload.header) -> None:
                self._draw_header(canvas, doc, header)

            templates.append(PageTemplate(id=f"p{index}", frames=[frame], onPage=draw_header, pagesize=page_size))
            if index > 0:
                story.extend([NextPageTemplate(f"p{index}"), PageBreak()])
            col_widths_pt = [max(px_to_points(c.width_px), 1.0) for c in payload.columns]
            table = Table(
                self._build_table_data(payload, col_widths_pt),
                colWidths=col_widths_pt,
                rowHeights=self._build_row_heights(payload),
                repeatRows=1,
            )
            table.setStyle(self._build_table_style(payload))
            story.append(table)

        document.addPageTemplates(templates)
        document.build(story, canvasmaker=_NumberedCanvas)

    def _build_table_data(self, payload: ExportPayload, col_widths_pt: list[float]) -> list[list]:
        header_style = ParagraphStyle(
            "header",
            fontName=FONT_NAME_BOLD,
            fontSize=payload.header_font_size,
            wordWrap="CJK" if payload.word_wrap else None,
        )
        data: list[list] = [
            [Paragraph(escape(column.name), header_style) for column in payload.columns]
        ]

        for row in payload.rows:
            if row.is_separator:
                data.append(["" for _ in payload.columns])
                continue
            cells = []
            for value, width_pt in zip(row.values, col_widths_pt):
                font_size = self._fit_font_size(
                    value, payload.font_size, width_pt, payload.min_font_size
                )
                if not payload.word_wrap:
                    # Überlauf abschneiden: Text auf Zellbreite kürzen
                    value = self._truncate_to_width(value, font_size, width_pt)
                style = ParagraphStyle(
                    "cell",
                    fontName=FONT_NAME,
                    fontSize=font_size,
                    leading=font_size * 1.2,
                    wordWrap="CJK" if payload.word_wrap else None,
                )
                cells.append(Paragraph(escape(value), style))
            data.append(cells)

        return data

    @staticmethod
    def _build_row_heights(payload: ExportPayload) -> list[float | None]:
        heights: list[float | None] = [px_to_points(payload.header_row_height_px)]
        data_row_height_pt = px_to_points(payload.row_height_px)
        for row in payload.rows:
            heights.append(px_to_points(payload.separator_height_px) if row.is_separator else data_row_height_pt)
        return heights

    @staticmethod
    def _fit_font_size(value: str, base_size: int, available_width_pt: float, min_size: int) -> int:
        if not value:
            return base_size
        usable_width = max(available_width_pt - CELL_PADDING_PT, 1.0)
        size = base_size
        while size > min_size:
            if stringWidth(value, FONT_NAME, size) <= usable_width:
                return size
            size -= 1
        return min_size

    @staticmethod
    def _truncate_to_width(value: str, font_size: int, available_width_pt: float) -> str:
        """Kürzt Text so, dass er in die Zellbreite passt (kein Zeilenumbruch)."""
        usable_width = max(available_width_pt - CELL_PADDING_PT, 1.0)
        if stringWidth(value, FONT_NAME, font_size) <= usable_width:
            return value
        ellipsis = "…"
        ellipsis_w = stringWidth(ellipsis, FONT_NAME, font_size)
        truncated = value
        while truncated and stringWidth(truncated, FONT_NAME, font_size) + ellipsis_w > usable_width:
            truncated = truncated[:-1]
        return truncated + ellipsis if truncated else ""

    @staticmethod
    def _build_table_style(payload: ExportPayload) -> TableStyle:
        commands = [
            ("FONTSIZE", (0, 0), (-1, 0), payload.header_font_size),
            ("FONTNAME", (0, 0), (-1, 0), FONT_NAME_BOLD),
            ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("LEFTPADDING", (0, 0), (-1, -1), 2),
            ("RIGHTPADDING", (0, 0), (-1, -1), 2),
            ("TOPPADDING", (0, 0), (-1, -1), 2),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
        ]
        data_row_counter = 0
        for table_row_index, row in enumerate(payload.rows, start=1):
            if row.is_separator:
                continue
            # Zeilenfarbe (Phase 2) hat Vorrang
            if row.row_color:
                commands.append(
                    ("BACKGROUND", (0, table_row_index), (-1, table_row_index),
                     colors.HexColor(row.row_color))
                )
            elif row.cell_colors:
                for col_idx, cell_color in enumerate(row.cell_colors):
                    if cell_color:
                        commands.append(
                            ("BACKGROUND", (col_idx, table_row_index), (col_idx, table_row_index),
                             colors.HexColor(cell_color))
                        )
            elif payload.alternate_row_colors and data_row_counter % 2 == 1:
                commands.append(
                    ("BACKGROUND", (0, table_row_index), (-1, table_row_index), ALTERNATE_ROW_COLOR)
                )
            data_row_counter += 1
        return TableStyle(commands)

    @staticmethod
    def _draw_header(canvas, doc, header: ExportHeaderConfig) -> None:
        canvas.saveState()
        canvas.setFont(FONT_NAME, 9)
        y = doc.pagesize[1] - MARGIN_PT - 16
        left_text = " | ".join(header.left)
        center_text = " | ".join(header.center)
        right_text = " | ".join(header.right)
        if left_text:
            canvas.drawString(doc.leftMargin, y, left_text)
        if center_text:
            canvas.drawCentredString(doc.pagesize[0] / 2, y, center_text)
        if right_text:
            canvas.drawRightString(doc.pagesize[0] - doc.rightMargin, y, right_text)
        canvas.restoreState()
