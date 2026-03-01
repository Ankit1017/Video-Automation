from __future__ import annotations

import sys
import types
import unittest

if "groq" not in sys.modules:
    groq_stub = types.ModuleType("groq")

    class _GroqStub:
        def __init__(self, *args, **kwargs):
            self.chat = types.SimpleNamespace(completions=types.SimpleNamespace(create=lambda **_kwargs: types.SimpleNamespace(choices=[])))

    groq_stub.Groq = _GroqStub
    sys.modules["groq"] = groq_stub

from main_app.ui.components.source_grounding import resolve_grounding_mode


class TestSourceGroundingComponentWebMode(unittest.TestCase):
    def test_mode_with_sources_stays_grounded(self) -> None:
        enabled, require_citations, warnings = resolve_grounding_mode(
            has_sources=True,
            strict_mode=False,
            require_citations=True,
        )
        self.assertTrue(enabled)
        self.assertTrue(require_citations)
        self.assertEqual(warnings, [])

    def test_mode_without_sources_falls_back_when_not_strict(self) -> None:
        enabled, require_citations, warnings = resolve_grounding_mode(
            has_sources=False,
            strict_mode=False,
            require_citations=True,
        )
        self.assertFalse(enabled)
        self.assertFalse(require_citations)
        self.assertTrue(any("Continuing in ungrounded mode" in item for item in warnings))

    def test_mode_without_sources_blocks_when_strict(self) -> None:
        enabled, require_citations, warnings = resolve_grounding_mode(
            has_sources=False,
            strict_mode=True,
            require_citations=True,
        )
        self.assertTrue(enabled)
        self.assertTrue(require_citations)
        self.assertTrue(any("Strict mode is enabled" in item for item in warnings))


if __name__ == "__main__":
    unittest.main()
