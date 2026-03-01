from __future__ import annotations

from main_app.contracts import RequirementSpecMap


INTENT_ORDER = [
    "topic",
    "mindmap",
    "flashcards",
    "data table",
    "quiz",
    "slideshow",
    "video",
    "audio_overview",
    "report",
]

INTENT_ALIASES = {
    "topic": "topic",
    "mindmap": "mindmap",
    "mind map": "mindmap",
    "flashcards": "flashcards",
    "flashcard": "flashcards",
    "data table": "data table",
    "data_table": "data table",
    "datatable": "data table",
    "quiz": "quiz",
    "slideshow": "slideshow",
    "slide show": "slideshow",
    "video": "video",
    "video builder": "video",
    "narrated video": "video",
    "video overview": "video",
    "narrated slideshow": "video",
    "audio_overview": "audio_overview",
    "audio overview": "audio_overview",
    "report": "report",
}

REQUIREMENT_SPEC: RequirementSpecMap = {
    "topic": {
        "mandatory": ["topic"],
        "optional": {
            "additional_instructions": {
                "label": "Additional Instructions",
                "type": "text",
                "default": "",
            },
        },
    },
    "mindmap": {
        "mandatory": ["topic"],
        "optional": {
            "max_depth": {
                "label": "Max Depth",
                "type": "int",
                "default": 4,
                "min": 2,
                "max": 8,
                "step": 1,
            },
            "constraints": {
                "label": "Constraints",
                "type": "text",
                "default": "",
            },
        },
    },
    "flashcards": {
        "mandatory": ["topic"],
        "optional": {
            "card_count": {
                "label": "Number of Cards",
                "type": "int",
                "default": 20,
                "min": 1,
                "max": 100,
                "step": 1,
            },
            "constraints": {
                "label": "Constraints",
                "type": "text",
                "default": "",
            },
        },
    },
    "data table": {
        "mandatory": ["topic"],
        "optional": {
            "row_count": {
                "label": "Rows",
                "type": "int",
                "default": 10,
                "min": 3,
                "max": 30,
                "step": 1,
            },
            "notes": {
                "label": "Notes",
                "type": "text",
                "default": "",
            },
        },
    },
    "quiz": {
        "mandatory": ["topic"],
        "optional": {
            "question_count": {
                "label": "Questions",
                "type": "int",
                "default": 10,
                "min": 3,
                "max": 25,
                "step": 1,
            },
            "difficulty": {
                "label": "Difficulty",
                "type": "enum",
                "default": "Intermediate",
                "options": ["Beginner", "Intermediate", "Advanced"],
            },
            "constraints": {
                "label": "Constraints",
                "type": "text",
                "default": "",
            },
        },
    },
    "slideshow": {
        "mandatory": ["topic"],
        "optional": {
            "subtopic_count": {
                "label": "Subtopics",
                "type": "int",
                "default": 5,
                "min": 2,
                "max": 10,
                "step": 1,
            },
            "slides_per_subtopic": {
                "label": "Slides per Subtopic",
                "type": "int",
                "default": 2,
                "min": 1,
                "max": 3,
                "step": 1,
            },
            "code_mode": {
                "label": "Code Mode",
                "type": "enum",
                "default": "auto",
                "options": ["auto", "force", "none"],
            },
            "representation_mode": {
                "label": "Representation Mode",
                "type": "enum",
                "default": "auto",
                "options": ["auto", "classic", "visual"],
            },
            "constraints": {
                "label": "Constraints",
                "type": "text",
                "default": "",
            },
        },
    },
    "audio_overview": {
        "mandatory": ["topic"],
        "optional": {
            "speaker_count": {
                "label": "Speakers",
                "type": "int",
                "default": 2,
                "min": 2,
                "max": 6,
                "step": 1,
            },
            "turn_count": {
                "label": "Dialogue Turns",
                "type": "int",
                "default": 12,
                "min": 6,
                "max": 28,
                "step": 2,
            },
            "conversation_style": {
                "label": "Conversation Style",
                "type": "enum",
                "default": "Educational Discussion",
                "options": ["Educational Discussion", "Interview", "Roundtable", "Debate"],
            },
            "language": {
                "label": "Audio Language",
                "type": "enum",
                "default": "en",
                "options": ["en", "hi", "es", "fr", "de", "ja"],
            },
            "slow_audio": {
                "label": "Slow Narration",
                "type": "bool",
                "default": False,
            },
            "youtube_prompt": {
                "label": "YouTube Style Prompt",
                "type": "bool",
                "default": False,
            },
            "hinglish_script": {
                "label": "Use Hinglish Script",
                "type": "bool",
                "default": False,
            },
            "constraints": {
                "label": "Constraints",
                "type": "text",
                "default": "",
            },
        },
    },
    "video": {
        "mandatory": ["topic"],
        "optional": {
            "subtopic_count": {
                "label": "Subtopics",
                "type": "int",
                "default": 5,
                "min": 2,
                "max": 10,
                "step": 1,
            },
            "slides_per_subtopic": {
                "label": "Slides per Subtopic",
                "type": "int",
                "default": 2,
                "min": 1,
                "max": 3,
                "step": 1,
            },
            "code_mode": {
                "label": "Code Mode",
                "type": "enum",
                "default": "auto",
                "options": ["auto", "force", "none"],
            },
            "speaker_count": {
                "label": "Voice Speakers",
                "type": "int",
                "default": 2,
                "min": 2,
                "max": 6,
                "step": 1,
            },
            "conversation_style": {
                "label": "Narration Style",
                "type": "enum",
                "default": "Educational Discussion",
                "options": ["Educational Discussion", "Interview", "Roundtable", "Debate"],
            },
            "language": {
                "label": "Audio Language",
                "type": "enum",
                "default": "en",
                "options": ["en", "hi", "es", "fr", "de", "ja"],
            },
            "slow_audio": {
                "label": "Slow Narration",
                "type": "bool",
                "default": False,
            },
            "video_template": {
                "label": "Video Template",
                "type": "enum",
                "default": "standard",
                "options": ["standard", "youtube"],
            },
            "animation_style": {
                "label": "Animation Style",
                "type": "enum",
                "default": "smooth",
                "options": ["none", "smooth", "youtube_dynamic"],
            },
            "representation_mode": {
                "label": "Representation Mode",
                "type": "enum",
                "default": "auto",
                "options": ["auto", "classic", "visual"],
            },
            "render_mode": {
                "label": "Render Mode",
                "type": "enum",
                "default": "avatar_conversation",
                "options": ["avatar_conversation", "classic_slides"],
            },
            "avatar_enable_subtitles": {
                "label": "Avatar Subtitles",
                "type": "bool",
                "default": True,
            },
            "avatar_style_pack": {
                "label": "Avatar Style Pack",
                "type": "enum",
                "default": "default",
                "options": ["default", "compact"],
            },
            "avatar_allow_fallback": {
                "label": "Avatar Auto Fallback",
                "type": "bool",
                "default": True,
            },
            "youtube_prompt": {
                "label": "YouTube Style Prompt",
                "type": "bool",
                "default": False,
            },
            "hinglish_script": {
                "label": "Use Hinglish Script",
                "type": "bool",
                "default": False,
            },
            "constraints": {
                "label": "Constraints",
                "type": "text",
                "default": "",
            },
        },
    },
    "report": {
        "mandatory": ["topic"],
        "optional": {
            "format_key": {
                "label": "Report Format",
                "type": "enum",
                "default": "briefing_doc",
                "options": ["briefing_doc", "study_guide", "blog_post"],
            },
            "additional_notes": {
                "label": "Additional Notes",
                "type": "text",
                "default": "",
            },
        },
    },
}

for _intent_key, _spec in REQUIREMENT_SPEC.items():
    if not isinstance(_spec, dict):
        continue
    _spec.setdefault("requirements_schema_key", _intent_key)
    _spec.setdefault("schema_version", "v1")
