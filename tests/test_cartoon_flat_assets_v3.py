from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path

from PIL import Image

from main_app.services.cartoon_asset_runtime_service import (
    resolve_asset_runtime_version,
    resolve_pack_root,
)
from main_app.services.cartoon_character_pack_service import CartoonCharacterPackService
from main_app.services.cartoon_flat_asset_catalog_service import CartoonFlatAssetCatalogService
from main_app.services.cartoon_flat_asset_sprite_service import CartoonFlatAssetSpriteService
from main_app.services.cartoon_flat_asset_validator import CartoonFlatAssetValidator


def _write_png(path: Path, *, size: tuple[int, int] = (320, 640), color: tuple[int, int, int, int] = (120, 170, 220, 255)) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGBA", size, color).save(path, format="PNG")


def _write_svg(path: Path, *, fill: str = "#EE7755") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        (
            '<svg xmlns="http://www.w3.org/2000/svg" width="320" height="640" viewBox="0 0 320 640">'
            f'<rect x="0" y="0" width="320" height="640" fill="{fill}" fill-opacity="0.2"/>'
            "</svg>"
        ),
        encoding="utf-8",
    )


def _create_minimal_flat_assets_pack(root: Path) -> None:
    _write_png(root / "Templates" / "Bust" / "peep-1.png", size=(400, 400))
    _write_png(root / "Templates" / "Standing" / "peep-standing-1.png", size=(380, 800))
    _write_png(root / "Templates" / "Sitting" / "peep-sitting-1.png", size=(420, 700))
    _write_svg(root / "Separate Atoms" / "face" / "Calm.svg", fill="#ffcc66")
    _write_svg(root / "Separate Atoms" / "face" / "Blank.svg", fill="#ddeeff")
    _write_svg(root / "Separate Atoms" / "head" / "Bangs.svg", fill="#555555")
    _write_svg(root / "Separate Atoms" / "body" / "Explaining.svg", fill="#4477dd")
    _write_svg(root / "Separate Atoms" / "pose" / "standing" / "pointing_finger-1.svg", fill="#88aa44")
    _write_svg(root / "Separate Atoms" / "pose" / "sitting" / "mid-1.svg", fill="#44aa88")
    _write_svg(root / "Separate Atoms" / "accessories" / "glasses.svg", fill="#aa66cc")
    _write_svg(root / "Separate Atoms" / "facial-hair" / "beard.svg", fill="#663300")


class TestCartoonFlatAssetsV3(unittest.TestCase):
    def test_runtime_resolver_uses_flat_assets_folder_name(self) -> None:
        with tempfile.TemporaryDirectory(prefix="flat_assets_runtime_") as temp_dir:
            flat_root = Path(temp_dir) / "flat_assets"
            flat_root.mkdir(parents=True, exist_ok=True)
            runtime = resolve_asset_runtime_version(pack_root=flat_root)
            self.assertEqual(runtime, "v3_flat_assets_direct")

    def test_pack_root_resolution_prefers_payload_then_env(self) -> None:
        with tempfile.TemporaryDirectory(prefix="flat_assets_pack_root_") as temp_dir:
            payload_root = Path(temp_dir) / "payload_pack"
            env_root = Path(temp_dir) / "env_pack"
            payload_root.mkdir(parents=True, exist_ok=True)
            env_root.mkdir(parents=True, exist_ok=True)
            prior = os.environ.get("CARTOON_PACK_ROOT")
            os.environ["CARTOON_PACK_ROOT"] = str(env_root)
            try:
                resolved = resolve_pack_root(payload={"metadata": {"pack": {"pack_root": str(payload_root)}}})
                self.assertEqual(resolved, payload_root)
                resolved_env = resolve_pack_root(payload=None)
                self.assertEqual(resolved_env, env_root)
            finally:
                if prior is None:
                    os.environ.pop("CARTOON_PACK_ROOT", None)
                else:
                    os.environ["CARTOON_PACK_ROOT"] = prior

    def test_manifestless_flat_assets_generates_v3_roster(self) -> None:
        with tempfile.TemporaryDirectory(prefix="flat_assets_roster_") as temp_dir:
            flat_root = Path(temp_dir) / "flat_assets"
            _create_minimal_flat_assets_pack(flat_root)
            service = CartoonCharacterPackService(pack_root=flat_root)
            roster = service.load_roster(speaker_count=2)
            self.assertEqual(len(roster), 2)
            for character in roster:
                self.assertEqual(str(character.get("asset_mode")), "flat_assets_direct")
            metadata = service.pack_metadata()
            self.assertEqual(metadata.get("pack_schema_version"), "v3_flat_assets")
            self.assertEqual(metadata.get("asset_runtime_version"), "v3_flat_assets_direct")

    def test_catalog_service_indexes_templates_and_atoms(self) -> None:
        with tempfile.TemporaryDirectory(prefix="flat_assets_catalog_") as temp_dir:
            flat_root = Path(temp_dir) / "flat_assets"
            _create_minimal_flat_assets_pack(flat_root)
            service = CartoonFlatAssetCatalogService(pack_root=flat_root)
            summary = service.summary()
            template_counts = summary.get("template_counts", {})
            atom_counts = summary.get("atom_counts", {})
            self.assertTrue(isinstance(template_counts, dict))
            self.assertTrue(isinstance(atom_counts, dict))
            self.assertGreaterEqual(int(template_counts.get("standing", 0)), 1)
            self.assertGreaterEqual(int(atom_counts.get("face", 0)), 1)
            profile = service.profile_for_character(character_id="ava")
            templates = profile.get("templates", {})
            self.assertTrue(isinstance(templates, dict))
            self.assertIsNotNone(templates.get("standing"))

    def test_sprite_service_is_deterministic(self) -> None:
        with tempfile.TemporaryDirectory(prefix="flat_assets_sprite_") as temp_dir:
            flat_root = Path(temp_dir) / "flat_assets"
            _create_minimal_flat_assets_pack(flat_root)
            sprite_service = CartoonFlatAssetSpriteService(pack_root=flat_root, disk_cache_root=Path(temp_dir) / ".cache")
            character = {"id": "ava", "asset_mode": "flat_assets_direct"}
            frame_a = sprite_service.render_sprite(
                character=character,
                state="talk",
                emotion="neutral",
                viseme="A",
                pose="idle",
                t_ms=420,
                target_size=(240, 420),
            )
            frame_b = sprite_service.render_sprite(
                character=character,
                state="talk",
                emotion="neutral",
                viseme="A",
                pose="idle",
                t_ms=420,
                target_size=(240, 420),
            )
            self.assertIsNotNone(frame_a)
            self.assertIsNotNone(frame_b)
            assert frame_a is not None and frame_b is not None
            self.assertEqual(frame_a.tobytes(), frame_b.tobytes())

    def test_validator_reports_missing_required_directories_with_paths(self) -> None:
        with tempfile.TemporaryDirectory(prefix="flat_assets_validator_missing_") as temp_dir:
            flat_root = Path(temp_dir) / "flat_assets"
            _write_png(flat_root / "Templates" / "Standing" / "peep-standing-1.png", size=(320, 720))
            validator = CartoonFlatAssetValidator(pack_root=flat_root)
            errors = validator.validate_roster(
                roster=[{"id": "ava", "asset_mode": "flat_assets_direct"}],
                timeline_schema_version="v2",
            )
            self.assertTrue(errors)
            expected_missing = str(flat_root / "Templates" / "Bust")
            self.assertTrue(any(expected_missing in error for error in errors))

    def test_validator_fails_when_cairosvg_is_unavailable(self) -> None:
        with tempfile.TemporaryDirectory(prefix="flat_assets_validator_cairosvg_") as temp_dir:
            flat_root = Path(temp_dir) / "flat_assets"
            _create_minimal_flat_assets_pack(flat_root)
            validator = CartoonFlatAssetValidator(pack_root=flat_root)
            original = CartoonFlatAssetValidator.__dict__["_has_cairosvg"]
            CartoonFlatAssetValidator._has_cairosvg = staticmethod(lambda: False)
            try:
                errors = validator.validate_roster(
                    roster=[{"id": "ava", "asset_mode": "flat_assets_direct"}],
                    timeline_schema_version="v2",
                )
                self.assertTrue(any("cairosvg" in error.lower() for error in errors))
            finally:
                CartoonFlatAssetValidator._has_cairosvg = original


if __name__ == "__main__":
    unittest.main()
