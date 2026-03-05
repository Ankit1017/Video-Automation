from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from main_app.services.cartoon_character_asset_validator import CartoonCharacterAssetValidator


class TestCartoonCharacterAssetValidator(unittest.TestCase):
    def test_validate_roster_passes_with_complete_cache_layout(self) -> None:
        with tempfile.TemporaryDirectory(prefix="cartoon_pack_") as temp_dir:
            pack_root = Path(temp_dir)
            cache_root = pack_root / "characters" / "ava" / "cache"
            self._build_complete_cache(cache_root)
            validator = CartoonCharacterAssetValidator(pack_root=pack_root)
            errors = validator.validate_roster(
                roster=[
                    {
                        "id": "ava",
                        "asset_mode": "lottie_cache",
                        "lottie_source": "characters/ava/lottie/main.json",
                        "cache_root": "characters/ava/cache",
                    }
                ],
                require_lottie_cache=True,
                timeline_schema_version="v2",
            )
            self.assertEqual(errors, [])

    def test_validate_roster_reports_missing_variant_path(self) -> None:
        with tempfile.TemporaryDirectory(prefix="cartoon_pack_") as temp_dir:
            pack_root = Path(temp_dir)
            cache_root = pack_root / "characters" / "ava" / "cache"
            self._build_complete_cache(cache_root)
            missing = cache_root / "talk" / "neutral_X" / "f0001.png"
            missing.unlink()

            validator = CartoonCharacterAssetValidator(pack_root=pack_root)
            errors = validator.validate_roster(
                roster=[
                    {
                        "id": "ava",
                        "asset_mode": "lottie_cache",
                        "lottie_source": "characters/ava/lottie/main.json",
                        "cache_root": "characters/ava/cache",
                    }
                ],
                require_lottie_cache=True,
                timeline_schema_version="v2",
            )
            self.assertTrue(any("neutral_X" in err for err in errors))

    def test_motion_quality_audit_warns_for_single_frame_variants(self) -> None:
        with tempfile.TemporaryDirectory(prefix="cartoon_pack_") as temp_dir:
            pack_root = Path(temp_dir)
            cache_root = pack_root / "characters" / "ava" / "cache"
            self._build_complete_cache(cache_root)
            validator = CartoonCharacterAssetValidator(pack_root=pack_root)
            warnings = validator.audit_roster_motion_quality(
                roster=[
                    {
                        "id": "ava",
                        "asset_mode": "lottie_cache",
                        "lottie_source": "characters/ava/lottie/main.json",
                        "cache_root": "characters/ava/cache",
                    }
                ],
                timeline_schema_version="v2",
                recommended_min_frames_per_variant=4,
            )
            self.assertTrue(any("low-motion variant" in warning for warning in warnings))

    @staticmethod
    def _build_complete_cache(cache_root: Path) -> None:
        emotions = ("neutral", "energetic", "tense", "warm", "inspiring")
        visemes = ("A", "B", "C", "D", "E", "F", "G", "H", "X")
        for state in ("idle", "blink"):
            for emotion in emotions:
                folder = cache_root / state / emotion
                folder.mkdir(parents=True, exist_ok=True)
                (folder / "f0001.png").write_bytes(b"\x89PNG\r\n\x1a\n")
        for emotion in emotions:
            for viseme in visemes:
                folder = cache_root / "talk" / f"{emotion}_{viseme}"
                folder.mkdir(parents=True, exist_ok=True)
                (folder / "f0001.png").write_bytes(b"\x89PNG\r\n\x1a\n")


if __name__ == "__main__":
    unittest.main()
