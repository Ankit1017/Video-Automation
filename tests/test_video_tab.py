from __future__ import annotations

import unittest

from main_app.ui.tabs.video_tab import _resolve_initial_playback_language


class TestVideoTabLanguageResolution(unittest.TestCase):
    def test_resolve_initial_playback_language_uses_hi_for_hinglish(self) -> None:
        resolved = _resolve_initial_playback_language(
            selected_language="en",
            use_hinglish_script=True,
        )
        self.assertEqual(resolved, "hi")

    def test_resolve_initial_playback_language_preserves_selected_without_hinglish(self) -> None:
        resolved = _resolve_initial_playback_language(
            selected_language="fr",
            use_hinglish_script=False,
        )
        self.assertEqual(resolved, "fr")


if __name__ == "__main__":
    unittest.main()
