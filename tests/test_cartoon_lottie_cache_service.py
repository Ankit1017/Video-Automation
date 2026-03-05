from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from main_app.services.cartoon_lottie_cache_service import CartoonLottieCacheService


class TestCartoonLottieCacheService(unittest.TestCase):
    def test_resolve_frame_path_uses_fallback_chain_for_talk_state(self) -> None:
        with tempfile.TemporaryDirectory(prefix="cartoon_lottie_cache_") as temp_dir:
            pack_root = Path(temp_dir)
            cache_root = pack_root / "characters" / "ava" / "cache"
            (cache_root / "talk" / "neutral_A").mkdir(parents=True, exist_ok=True)
            (cache_root / "talk" / "neutral_A" / "f0001.png").write_bytes(b"\x89PNG\r\n\x1a\n")

            service = CartoonLottieCacheService(pack_root=pack_root)
            frame = service.resolve_frame_path(
                character={"id": "ava", "cache_root": "characters/ava/cache"},
                state="talk",
                emotion="energetic",
                viseme="A",
                t_ms=100,
                cache_fps=24,
            )
            self.assertIn("neutral_A", str(frame))

    def test_resolve_frame_path_raises_when_no_variant_exists(self) -> None:
        with tempfile.TemporaryDirectory(prefix="cartoon_lottie_cache_") as temp_dir:
            pack_root = Path(temp_dir)
            service = CartoonLottieCacheService(pack_root=pack_root)
            with self.assertRaises(FileNotFoundError):
                _ = service.resolve_frame_path(
                    character={"id": "ava", "cache_root": "characters/ava/cache"},
                    state="talk",
                    emotion="neutral",
                    viseme="X",
                    t_ms=0,
                    cache_fps=24,
                )
            self.assertGreaterEqual(service.cache_miss_count, 1)

    def test_resolve_frame_path_uses_cache_fps_for_indexing(self) -> None:
        with tempfile.TemporaryDirectory(prefix="cartoon_lottie_cache_") as temp_dir:
            pack_root = Path(temp_dir)
            cache_root = pack_root / "characters" / "ava" / "cache" / "idle" / "neutral"
            cache_root.mkdir(parents=True, exist_ok=True)
            (cache_root / "f0001.png").write_bytes(b"\x89PNG\r\n\x1a\n")
            (cache_root / "f0002.png").write_bytes(b"\x89PNG\r\n\x1a\n")
            (cache_root / "f0003.png").write_bytes(b"\x89PNG\r\n\x1a\n")
            (cache_root / "f0004.png").write_bytes(b"\x89PNG\r\n\x1a\n")

            service = CartoonLottieCacheService(pack_root=pack_root)
            frame = service.resolve_frame_path(
                character={"id": "ava", "cache_root": "characters/ava/cache"},
                state="idle",
                emotion="neutral",
                viseme="X",
                t_ms=250,
                cache_fps=8,
            )
            self.assertTrue(str(frame).endswith("f0003.png"))


if __name__ == "__main__":
    unittest.main()
