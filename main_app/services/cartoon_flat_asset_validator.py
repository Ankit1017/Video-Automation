from __future__ import annotations

import importlib.util
from pathlib import Path

from main_app.contracts import CartoonCharacterSpec
from main_app.services.cartoon_flat_asset_catalog_service import CartoonFlatAssetCatalogService


class CartoonFlatAssetValidator:
    REQUIRED_TEMPLATE_DIRS: tuple[tuple[str, ...], ...] = (
        ("Templates", "Bust"),
        ("Templates", "Standing"),
        ("Templates", "Sitting"),
    )
    REQUIRED_ATOM_DIRS: tuple[tuple[str, ...], ...] = (
        ("Separate Atoms", "face"),
        ("Separate Atoms", "head"),
        ("Separate Atoms", "body"),
        ("Separate Atoms", "pose", "standing"),
        ("Separate Atoms", "pose", "sitting"),
    )
    OPTIONAL_ATOM_DIRS: tuple[tuple[str, ...], ...] = (
        ("Separate Atoms", "accessories"),
        ("Separate Atoms", "facial-hair"),
    )

    def __init__(self, *, pack_root: Path, catalog_service: CartoonFlatAssetCatalogService | None = None) -> None:
        self._pack_root = pack_root
        self._catalog_service = catalog_service or CartoonFlatAssetCatalogService(pack_root=pack_root)

    def validate_roster(
        self,
        *,
        roster: list[CartoonCharacterSpec],
        timeline_schema_version: str,
    ) -> list[str]:
        if _clean(timeline_schema_version).lower() != "v2":
            return []
        errors: list[str] = []
        if not self._has_cairosvg():
            errors.append("Flat-assets runtime requires `cairosvg` (`pip install cairosvg`) for SVG atom rasterization.")
        for parts in self.REQUIRED_TEMPLATE_DIRS + self.REQUIRED_ATOM_DIRS:
            path = self._pack_root.joinpath(*parts)
            if not path.exists() or not path.is_dir():
                errors.append(f"Flat-assets required directory missing: {path}")
        summary = self.catalog_summary()
        template_counts = summary.get("template_counts", {})
        atom_counts = summary.get("atom_counts", {})
        if isinstance(template_counts, dict):
            for key in ("bust", "standing", "sitting"):
                count = _int_safe(template_counts.get(key), default=0)
                if count <= 0:
                    errors.append(f"Flat-assets template set `{key}` has no PNG files under `{self._pack_root}`.")
        if isinstance(atom_counts, dict):
            for key in ("face", "head", "body", "pose_standing", "pose_sitting"):
                count = _int_safe(atom_counts.get(key), default=0)
                if count <= 0:
                    errors.append(f"Flat-assets atom set `{key}` has no usable files under `{self._pack_root}`.")

        for character in roster:
            char_id = _clean(character.get("id")) or "unknown"
            if _clean(character.get("asset_mode")).lower() != "flat_assets_direct":
                errors.append(f"Character `{char_id}` asset_mode must be `flat_assets_direct` for flat-assets runtime.")
        return errors

    def audit_roster_motion_quality(
        self,
        *,
        roster: list[CartoonCharacterSpec],
        timeline_schema_version: str,
    ) -> list[str]:
        if _clean(timeline_schema_version).lower() != "v2":
            return []
        warnings: list[str] = []
        summary = self.catalog_summary()
        template_counts = summary.get("template_counts", {})
        atom_counts = summary.get("atom_counts", {})
        if isinstance(template_counts, dict):
            standing_count = _int_safe(template_counts.get("standing"), default=0)
            sitting_count = _int_safe(template_counts.get("sitting"), default=0)
            bust_count = _int_safe(template_counts.get("bust"), default=0)
            if standing_count < 6:
                warnings.append(
                    f"Flat-assets low variety: `Templates/Standing` has {standing_count} file(s). Recommended >= 6."
                )
            if sitting_count < 4:
                warnings.append(
                    f"Flat-assets low variety: `Templates/Sitting` has {sitting_count} file(s). Recommended >= 4."
                )
            if bust_count < 8:
                warnings.append(
                    f"Flat-assets low variety: `Templates/Bust` has {bust_count} file(s). Recommended >= 8."
                )
        if isinstance(atom_counts, dict):
            face_count = _int_safe(atom_counts.get("face"), default=0)
            pose_standing_count = _int_safe(atom_counts.get("pose_standing"), default=0)
            pose_sitting_count = _int_safe(atom_counts.get("pose_sitting"), default=0)
            accessories_count = _int_safe(atom_counts.get("accessories"), default=0)
            facial_hair_count = _int_safe(atom_counts.get("facial_hair"), default=0)
            if face_count < 12:
                warnings.append(
                    f"Flat-assets low variety: `Separate Atoms/face` has {face_count} file(s). Recommended >= 12."
                )
            if pose_standing_count < 6:
                warnings.append(
                    f"Flat-assets low variety: `Separate Atoms/pose/standing` has {pose_standing_count} file(s). Recommended >= 6."
                )
            if pose_sitting_count < 4:
                warnings.append(
                    f"Flat-assets low variety: `Separate Atoms/pose/sitting` has {pose_sitting_count} file(s). Recommended >= 4."
                )
            if accessories_count <= 0:
                warnings.append("Flat-assets optional set `Separate Atoms/accessories` is empty.")
            if facial_hair_count <= 0:
                warnings.append("Flat-assets optional set `Separate Atoms/facial-hair` is empty.")
        if roster:
            warnings.append(
                f"Flat-assets v3 roster count: {len(roster)} character(s), pack_root={self._pack_root}."
            )
        return warnings

    def motion_quality_summary(
        self,
        *,
        roster: list[CartoonCharacterSpec],
        timeline_schema_version: str,
    ) -> dict[str, dict[str, int]]:
        if _clean(timeline_schema_version).lower() != "v2":
            return {}
        summary = self.catalog_summary()
        template_counts = summary.get("template_counts", {})
        atom_counts = summary.get("atom_counts", {})
        result: dict[str, dict[str, int]] = {}
        for character in roster:
            char_id = _clean(character.get("id")) or "unknown"
            result[char_id] = {
                "template_standing": _int_safe(template_counts.get("standing") if isinstance(template_counts, dict) else 0, default=0),
                "template_sitting": _int_safe(template_counts.get("sitting") if isinstance(template_counts, dict) else 0, default=0),
                "template_bust": _int_safe(template_counts.get("bust") if isinstance(template_counts, dict) else 0, default=0),
                "atom_face": _int_safe(atom_counts.get("face") if isinstance(atom_counts, dict) else 0, default=0),
                "atom_pose_standing": _int_safe(atom_counts.get("pose_standing") if isinstance(atom_counts, dict) else 0, default=0),
                "atom_pose_sitting": _int_safe(atom_counts.get("pose_sitting") if isinstance(atom_counts, dict) else 0, default=0),
            }
        return result

    def catalog_summary(self) -> dict[str, object]:
        return self._catalog_service.summary()

    @staticmethod
    def _has_cairosvg() -> bool:
        return importlib.util.find_spec("cairosvg") is not None


def _clean(value: object) -> str:
    return " ".join(str(value or "").split()).strip()


def _int_safe(value: object, *, default: int) -> int:
    try:
        if isinstance(value, bool):
            return default
        if isinstance(value, (int, float, str)):
            return int(value)
        return int(str(value))
    except (TypeError, ValueError):
        return default
