from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Literal, cast


CartoonAssetRuntimeVersion = Literal["v2_lottie_cache", "v3_flat_assets_direct"]


def default_cartoon_pack_root() -> Path:
    return Path(__file__).resolve().parents[1] / "assets" / "cartoon_packs" / "default"


def resolve_pack_root(
    *,
    payload: dict[str, Any] | None = None,
    explicit_pack_root: Path | None = None,
) -> Path:
    if explicit_pack_root is not None:
        return explicit_pack_root
    payload_path = pack_root_from_payload(payload=payload)
    if payload_path is not None:
        return payload_path
    env_path = env_pack_root()
    if env_path is not None:
        return env_path
    return default_cartoon_pack_root()


def env_pack_root() -> Path | None:
    raw = _clean(os.getenv("CARTOON_PACK_ROOT", ""))
    if not raw:
        return None
    return Path(raw).expanduser()


def pack_root_from_payload(*, payload: dict[str, Any] | None) -> Path | None:
    if not isinstance(payload, dict):
        return None
    metadata = payload.get("metadata", {})
    metadata_map = metadata if isinstance(metadata, dict) else {}
    pack = metadata_map.get("pack")
    if isinstance(pack, dict):
        pack_root = _clean(pack.get("pack_root"))
        if pack_root:
            return Path(pack_root)
    direct_root = _clean(metadata_map.get("asset_pack_root"))
    if direct_root:
        return Path(direct_root)
    return None


def resolve_asset_runtime_version(*, pack_root: Path) -> CartoonAssetRuntimeVersion:
    if pack_root.name.strip().lower() == "flat_assets":
        return cast(CartoonAssetRuntimeVersion, "v3_flat_assets_direct")
    return cast(CartoonAssetRuntimeVersion, "v2_lottie_cache")


def resolve_pack_kind(*, pack_root: Path, runtime_version: CartoonAssetRuntimeVersion | None = None) -> str:
    resolved_runtime = runtime_version or resolve_asset_runtime_version(pack_root=pack_root)
    if resolved_runtime == "v3_flat_assets_direct":
        return "flat_assets"
    return "lottie_cache_pack"


def runtime_metadata(*, pack_root: Path, runtime_version: CartoonAssetRuntimeVersion | None = None) -> dict[str, object]:
    resolved_runtime = runtime_version or resolve_asset_runtime_version(pack_root=pack_root)
    return {
        "asset_runtime_version": resolved_runtime,
        "asset_pack_root": str(pack_root),
        "asset_pack_kind": resolve_pack_kind(pack_root=pack_root, runtime_version=resolved_runtime),
    }


def _clean(value: object) -> str:
    return " ".join(str(value or "").split()).strip()
