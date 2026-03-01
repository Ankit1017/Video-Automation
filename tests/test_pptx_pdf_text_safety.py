from __future__ import annotations

import unittest

from main_app.services.pptx_export.pdf_builder import PdfDeckBuilder


class TestPptxPdfTextSafety(unittest.TestCase):
    def test_to_pdf_safe_text_replaces_problematic_unicode(self) -> None:
        value = "Bullet \u2022 dash \u2014 quote \u201ctext\u201d caf\u00e9"
        safe = PdfDeckBuilder._to_pdf_safe_text(value)
        self.assertEqual(safe, 'Bullet - dash - quote "text" cafe')

    def test_to_pdf_safe_text_replaces_ligatures(self) -> None:
        value = "Work\ufb02ows are prede\ufb01ned"
        safe = PdfDeckBuilder._to_pdf_safe_text(value)
        self.assertEqual(safe, "Workflows are predefined")

    def test_to_pdf_safe_text_preserves_spacing_when_requested(self) -> None:
        value = "line  with\tspacing"
        safe = PdfDeckBuilder._to_pdf_safe_text(value, preserve_spacing=True)
        self.assertEqual(safe, "line  with\tspacing")


if __name__ == "__main__":
    unittest.main()
