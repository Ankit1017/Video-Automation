from __future__ import annotations

import unittest

from main_app.platform.web_sourcing.query_strategy import build_query_variants, tokenize_text


class TestWebSourcingQueryStrategy(unittest.TestCase):
    def test_build_query_variants_applies_typo_fix_and_caps_count(self) -> None:
        variants = build_query_variants(
            " Tranformers how tranformers help AI ",
            max_variants=4,
        )
        self.assertGreaterEqual(len(variants), 3)
        self.assertEqual(variants[0], "Tranformers how tranformers help AI")
        self.assertIn("transformers", variants[1].lower())
        self.assertLessEqual(len(variants), 4)

    def test_build_query_variants_handles_empty(self) -> None:
        variants = build_query_variants("  ", max_variants=3)
        self.assertEqual(variants, [])

    def test_tokenize_text_normalizes_tokens(self) -> None:
        tokens = tokenize_text("Agentic-AI workflows for LLMs!!")
        self.assertIn("agentic", tokens)
        self.assertIn("workflows", tokens)
        self.assertIn("llms", tokens)


if __name__ == "__main__":
    unittest.main()
