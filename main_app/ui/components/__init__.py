"""Reusable UI components shared by tabs and dashboard."""

from main_app.ui.components.flashcards_view import FlashcardsRenderConfig, render_flashcards_view
from main_app.ui.components.background_job_view import render_background_job_panel
from main_app.ui.components.cartoon_view import CartoonRenderConfig, render_cartoon_view
from main_app.ui.components.quiz_view import QuizRenderConfig, render_quiz_view
from main_app.ui.components.report_view import ReportRenderConfig, render_report_view
from main_app.ui.components.slideshow_view import SlideshowRenderConfig, render_slideshow_view
from main_app.ui.components.source_grounding import (
    SourceGroundingSelection,
    render_source_grounding_controls,
)
from main_app.ui.components.video_view import VideoRenderConfig, render_video_view

__all__ = [
    "FlashcardsRenderConfig",
    "QuizRenderConfig",
    "ReportRenderConfig",
    "SlideshowRenderConfig",
    "SourceGroundingSelection",
    "CartoonRenderConfig",
    "VideoRenderConfig",
    "render_background_job_panel",
    "render_cartoon_view",
    "render_flashcards_view",
    "render_quiz_view",
    "render_report_view",
    "render_slideshow_view",
    "render_source_grounding_controls",
    "render_video_view",
]
