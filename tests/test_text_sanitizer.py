from __future__ import annotations

import unittest

from main_app.services.text_sanitizer import sanitize_text


class TestTextSanitizer(unittest.TestCase):
    def test_sanitize_text_replaces_unicode_ligatures(self) -> None:
        value = "Work\ufb02ows are prede\ufb01ned"
        cleaned = sanitize_text(value, keep_citations=True)
        self.assertEqual(cleaned, "Workflows are predefined")

    def test_sanitize_text_recovers_black_square_ligature_placeholders(self) -> None:
        value = "Work\u25a0ows and prede\u25a0ned tasks are well-de\u25a0ned"
        cleaned = sanitize_text(value, keep_citations=True)
        self.assertEqual(cleaned, "Workflows and predefined tasks are well-defined")

    def test_sanitize_text_repairs_common_mojibake_ligatures(self) -> None:
        value = "Work\u00ef\u00ac\u0082ows and prede\u00ef\u00ac\u0081ned paths"
        cleaned = sanitize_text(value, keep_citations=True)
        self.assertEqual(cleaned, "Workflows and predefined paths")


if __name__ == "__main__":
    unittest.main()
