"""Darstellungsoptionen für Vorschau, Excel- und PDF-Export."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass
class DisplayConfig:
    font_size: int = 10
    alternate_row_colors: bool = False
    landscape: bool = False
    row_height_px: int = 20
    header_font_size: int = 10
    header_row_height_px: int = 20
    word_wrap: bool = True
    min_font_size: int = 5
