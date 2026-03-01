from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal


BrandedLayoutType = Literal[
    "summary",
    "split_code",
    "dual_column",
    "timeline",
    "process_flow",
    "metric_cards",
]


@dataclass(frozen=True)
class TypographyTokens:
    title_font: str = "Calibri"
    subtitle_font: str = "Calibri"
    body_font: str = "Calibri"
    caption_font: str = "Calibri"
    code_font: str = "Consolas"
    title_size: int = 34
    subtitle_size: int = 20
    body_size: int = 20
    caption_size: int = 12
    code_size: int = 12


@dataclass(frozen=True)
class SpacingTokens:
    outer_margin_x_in: float = 0.7
    outer_margin_y_in: float = 0.7
    content_gutter_in: float = 0.25
    title_gap_in: float = 0.25
    footer_height_in: float = 0.35
    section_chip_padding_in: float = 0.08


@dataclass(frozen=True)
class ShapeTokens:
    rounded_radius_pt: int = 8
    accent_bar_height_in: float = 0.22
    border_width_pt: int = 1


@dataclass(frozen=True)
class BrandingTokens:
    logo_path: str = ""
    footer_logo_path: str = ""
    footer_text: str = ""
    show_footer_logo: bool = True
    show_title_logo: bool = True


@dataclass(frozen=True)
class LayoutPlan:
    layout_type: BrandedLayoutType
    title: str
    section: str
    bullets: list[str] = field(default_factory=list)
    code_snippet: str = ""
    code_language: str = "text"
    left_title: str = ""
    right_title: str = ""
    left_items: list[str] = field(default_factory=list)
    right_items: list[str] = field(default_factory=list)
    events: list[dict[str, str]] = field(default_factory=list)
    steps: list[dict[str, str]] = field(default_factory=list)
    cards: list[dict[str, str]] = field(default_factory=list)
    speaker_notes: str = ""


@dataclass(frozen=True)
class DeckThemeSpec:
    key: str
    title: str
    description: str
    font_name: str
    background_color: tuple[int, int, int]
    accent_color: tuple[int, int, int]
    title_color: tuple[int, int, int]
    body_color: tuple[int, int, int]
    section_chip_color: tuple[int, int, int]
    section_chip_text_color: tuple[int, int, int]
    code_panel_color: tuple[int, int, int]
    code_text_color: tuple[int, int, int]
    typography: TypographyTokens = field(default_factory=TypographyTokens)
    spacing: SpacingTokens = field(default_factory=SpacingTokens)
    shapes: ShapeTokens = field(default_factory=ShapeTokens)
    branding: BrandingTokens = field(default_factory=BrandingTokens)
    # Inches: x, y, width, height by preset key.
    layout_presets: dict[str, tuple[float, float, float, float]] = field(default_factory=dict)


@dataclass(frozen=True)
class PptxTemplateStyle(DeckThemeSpec):
    pass
