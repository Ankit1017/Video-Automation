from __future__ import annotations

import argparse
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timezone
import fnmatch
import json
from pathlib import Path
import shutil
from typing import Any
from zipfile import ZipFile


JUNK_FILE_NAMES = {".ds_store", "thumbs.db"}
JUNK_PARTS = {"__macosx"}
DEFAULT_ALLOWED_EXTENSIONS = {
    ".png",
    ".jpg",
    ".jpeg",
    ".webp",
    ".svg",
    ".json",
    ".txt",
    ".md",
    ".csv",
    ".ai",
    ".fig",
    ".sketch",
    ".studio",
}
DEFAULT_SKIP_ARCHIVE_PATTERNS = {
    "openmoji-618x618-black.zip",
    "openmoji-618x618-color.zip",
    "openmoji-72x72-black.zip",
    "openmoji-72x72-color.zip",
    "openmoji-font.zip",
    "openmoji-svg-black.zip",
}


@dataclass(frozen=True)
class ArchiveResult:
    name: str
    slug: str
    skipped: bool
    skip_reason: str
    extracted_files: int
    normalized_files: int
    extracted_path: str
    normalized_path: str
    extension_counts: dict[str, int]
    license_files: list[str]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Extract and normalize third-party asset archives into a stable local structure.",
    )
    parser.add_argument(
        "--source-root",
        type=str,
        default="main_app/assets/open-source_packs",
        help="Source directory containing zip archives and design source files.",
    )
    parser.add_argument(
        "--raw-root",
        type=str,
        default="raw",
        help="Subdirectory under source root for copied archives and extracted raw content.",
    )
    parser.add_argument(
        "--normalized-root",
        type=str,
        default="normalized",
        help="Subdirectory under source root for cleaned/normalized files.",
    )
    parser.add_argument(
        "--inventory-file",
        type=str,
        default="inventory.json",
        help="Inventory filename under source root.",
    )
    parser.add_argument(
        "--extract-nested-zips",
        action="store_true",
        help="Extract nested zip files discovered after main extraction.",
    )
    parser.add_argument(
        "--clear-output",
        action="store_true",
        help="Delete raw and normalized outputs before processing.",
    )
    parser.add_argument(
        "--include-ext",
        action="append",
        default=None,
        help="Extra extension to preserve in normalized output (e.g. --include-ext .pdf).",
    )
    parser.add_argument(
        "--skip-archive-pattern",
        action="append",
        default=None,
        help="Filename glob to skip (can be repeated).",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Print detailed per-archive actions.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    source_root = Path(args.source_root).resolve()
    if not source_root.exists() or not source_root.is_dir():
        raise FileNotFoundError(f"Source root not found: {source_root}")

    raw_root = source_root / str(args.raw_root).strip()
    normalized_root = source_root / str(args.normalized_root).strip()
    archives_root = raw_root / "archives"
    extracted_root = raw_root / "extracted"
    design_root = raw_root / "design_sources"
    inventory_path = source_root / str(args.inventory_file).strip()
    allowed_exts = set(DEFAULT_ALLOWED_EXTENSIONS)
    for extra in args.include_ext or []:
        normalized = _normalize_extension(extra)
        if normalized:
            allowed_exts.add(normalized)

    skip_patterns = set(DEFAULT_SKIP_ARCHIVE_PATTERNS)
    for pattern in args.skip_archive_pattern or []:
        clean_pattern = " ".join(str(pattern).split()).strip()
        if clean_pattern:
            skip_patterns.add(clean_pattern)

    if args.clear_output:
        for path in (raw_root, normalized_root):
            if path.exists():
                shutil.rmtree(path, ignore_errors=True)

    archives_root.mkdir(parents=True, exist_ok=True)
    extracted_root.mkdir(parents=True, exist_ok=True)
    design_root.mkdir(parents=True, exist_ok=True)
    normalized_root.mkdir(parents=True, exist_ok=True)

    design_sources = _collect_design_sources(source_root=source_root)
    copied_design_files = _copy_design_sources(design_sources=design_sources, design_root=design_root)

    archive_results: list[ArchiveResult] = []
    archive_paths = sorted(source_root.glob("*.zip"), key=lambda path: path.name.lower())
    for archive_path in archive_paths:
        result = _process_archive(
            archive_path=archive_path,
            archives_root=archives_root,
            extracted_root=extracted_root,
            normalized_root=normalized_root,
            allowed_extensions=allowed_exts,
            skip_patterns=skip_patterns,
            extract_nested_zips=bool(args.extract_nested_zips),
            verbose=bool(args.verbose),
        )
        archive_results.append(result)

    inventory = {
        "generated_at": _utc_now_iso(),
        "source_root": str(source_root),
        "raw_root": str(raw_root),
        "normalized_root": str(normalized_root),
        "archives_total": len(archive_results),
        "archives_processed": len([item for item in archive_results if not item.skipped]),
        "archives_skipped": len([item for item in archive_results if item.skipped]),
        "archives": [archive_result_to_dict(item) for item in archive_results],
        "design_sources_total": len(design_sources),
        "design_sources_copied": len(copied_design_files),
        "design_sources": [str(path.relative_to(source_root)) for path in copied_design_files],
    }
    inventory_path.write_text(json.dumps(inventory, ensure_ascii=True, indent=2, sort_keys=True), encoding="utf-8")

    print(f"Source root: {source_root}")
    print(f"Archives found: {len(archive_results)}")
    print(f"Archives processed: {inventory['archives_processed']}")
    print(f"Archives skipped: {inventory['archives_skipped']}")
    print(f"Design source files copied: {len(copied_design_files)}")
    print(f"Inventory written: {inventory_path}")
    return 0


def _process_archive(
    *,
    archive_path: Path,
    archives_root: Path,
    extracted_root: Path,
    normalized_root: Path,
    allowed_extensions: set[str],
    skip_patterns: set[str],
    extract_nested_zips: bool,
    verbose: bool,
) -> ArchiveResult:
    slug = _slugify(archive_path.stem) or "archive"
    copied_archive_path = archives_root / archive_path.name
    extracted_path = extracted_root / slug
    normalized_path = normalized_root / slug

    should_skip = _matches_any_glob(archive_path.name, skip_patterns)
    if should_skip:
        if verbose:
            print(f"[skip] {archive_path.name} -> matched skip pattern")
        _copy_file(archive_path, copied_archive_path)
        return ArchiveResult(
            name=archive_path.name,
            slug=slug,
            skipped=True,
            skip_reason="matched skip pattern",
            extracted_files=0,
            normalized_files=0,
            extracted_path=str(extracted_path),
            normalized_path=str(normalized_path),
            extension_counts={},
            license_files=[],
        )

    _copy_file(archive_path, copied_archive_path)
    if extracted_path.exists():
        shutil.rmtree(extracted_path, ignore_errors=True)
    extracted_path.mkdir(parents=True, exist_ok=True)

    extracted_count = _extract_zip(archive_path=copied_archive_path, destination=extracted_path)
    if extract_nested_zips:
        extracted_count += _extract_nested_archives(root=extracted_path, verbose=verbose)
    _remove_junk_entries(extracted_path)

    if normalized_path.exists():
        shutil.rmtree(normalized_path, ignore_errors=True)
    normalized_path.mkdir(parents=True, exist_ok=True)

    source_for_normalization = _collapse_single_root(extracted_path)
    normalized_files, extension_counts, license_files = _copy_normalized_files(
        source_root=source_for_normalization,
        destination_root=normalized_path,
        allowed_extensions=allowed_extensions,
    )
    if verbose:
        print(
            f"[ok] {archive_path.name}: extracted={extracted_count}, normalized={normalized_files}, "
            f"licenses={len(license_files)}"
        )
    return ArchiveResult(
        name=archive_path.name,
        slug=slug,
        skipped=False,
        skip_reason="",
        extracted_files=extracted_count,
        normalized_files=normalized_files,
        extracted_path=str(extracted_path),
        normalized_path=str(normalized_path),
        extension_counts=dict(extension_counts),
        license_files=license_files,
    )


def _collect_design_sources(*, source_root: Path) -> list[Path]:
    files: list[Path] = []
    for path in sorted(source_root.iterdir(), key=lambda item: item.name.lower()):
        if not path.is_file():
            continue
        if path.suffix.lower() in {".zip", ".json"}:
            continue
        if _is_junk_name(path.name):
            continue
        files.append(path)
    return files


def _copy_design_sources(*, design_sources: list[Path], design_root: Path) -> list[Path]:
    copied: list[Path] = []
    for path in design_sources:
        target = design_root / path.name
        _copy_file(path, target)
        copied.append(target)
    return copied


def _copy_normalized_files(
    *,
    source_root: Path,
    destination_root: Path,
    allowed_extensions: set[str],
) -> tuple[int, Counter[str], list[str]]:
    copied_count = 0
    extension_counts: Counter[str] = Counter()
    license_files: list[str] = []
    for file_path in sorted(source_root.rglob("*"), key=lambda item: str(item).lower()):
        if not file_path.is_file():
            continue
        if _is_junk_path(file_path):
            continue
        suffix = file_path.suffix.lower()
        keep = suffix in allowed_extensions or _looks_like_license_or_readme(file_path.name)
        if not keep:
            continue
        relative = file_path.relative_to(source_root)
        target = destination_root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(file_path, target)
        copied_count += 1
        extension_counts[suffix or "<noext>"] += 1
        if _looks_like_license_or_readme(file_path.name):
            license_files.append(str(relative))
    return copied_count, extension_counts, sorted(set(license_files))


def _extract_zip(*, archive_path: Path, destination: Path) -> int:
    extracted_files = 0
    with ZipFile(archive_path) as zip_file:
        for member in zip_file.infolist():
            member_name = member.filename.replace("\\", "/")
            if member.is_dir() or _is_junk_member_name(member_name):
                continue
            zip_file.extract(member, destination)
            extracted_files += 1
    return extracted_files


def _extract_nested_archives(*, root: Path, verbose: bool) -> int:
    total_extracted = 0
    nested_archives = sorted(root.rglob("*.zip"), key=lambda path: str(path).lower())
    for nested in nested_archives:
        if _is_junk_path(nested):
            continue
        nested_target = nested.parent / f"{nested.stem}__nested"
        nested_target.mkdir(parents=True, exist_ok=True)
        extracted = _extract_zip(archive_path=nested, destination=nested_target)
        total_extracted += extracted
        if verbose:
            print(f"  nested: {nested} -> {nested_target} ({extracted} files)")
    return total_extracted


def _remove_junk_entries(root: Path) -> None:
    for path in sorted(root.rglob("*"), key=lambda item: len(item.parts), reverse=True):
        if path.is_file() and _is_junk_name(path.name):
            path.unlink(missing_ok=True)
            continue
        if path.is_dir() and path.name.lower() in JUNK_PARTS:
            shutil.rmtree(path, ignore_errors=True)
    # remove AppleDouble files generated during extraction
    for path in sorted(root.rglob("._*"), key=lambda item: str(item).lower()):
        if path.is_file():
            path.unlink(missing_ok=True)


def _collapse_single_root(path: Path) -> Path:
    current = path
    while True:
        files = [item for item in current.iterdir() if item.is_file() and not _is_junk_name(item.name)]
        dirs = [item for item in current.iterdir() if item.is_dir() and item.name.lower() not in JUNK_PARTS]
        if files:
            return current
        if len(dirs) != 1:
            return current
        current = dirs[0]


def _copy_file(source: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, destination)


def archive_result_to_dict(result: ArchiveResult) -> dict[str, Any]:
    return {
        "name": result.name,
        "slug": result.slug,
        "skipped": result.skipped,
        "skip_reason": result.skip_reason,
        "extracted_files": result.extracted_files,
        "normalized_files": result.normalized_files,
        "extracted_path": result.extracted_path,
        "normalized_path": result.normalized_path,
        "extension_counts": dict(sorted(result.extension_counts.items())),
        "license_files": result.license_files,
    }


def _matches_any_glob(name: str, patterns: set[str]) -> bool:
    lowered = name.lower()
    for pattern in patterns:
        if fnmatch.fnmatch(lowered, pattern.lower()):
            return True
    return False


def _slugify(text: str) -> str:
    safe = []
    for ch in str(text).strip().lower():
        if ch.isalnum():
            safe.append(ch)
        else:
            safe.append("_")
    raw = "".join(safe).strip("_")
    while "__" in raw:
        raw = raw.replace("__", "_")
    return raw


def _is_junk_member_name(name: str) -> bool:
    parts = [part for part in name.split("/") if part]
    if not parts:
        return True
    if any(part.lower() in JUNK_PARTS for part in parts):
        return True
    base_name = parts[-1]
    if _is_junk_name(base_name):
        return True
    return False


def _is_junk_name(name: str) -> bool:
    lowered = str(name).strip().lower()
    return lowered in JUNK_FILE_NAMES or lowered.startswith("._")


def _is_junk_path(path: Path) -> bool:
    if _is_junk_name(path.name):
        return True
    return any(part.lower() in JUNK_PARTS for part in path.parts)


def _looks_like_license_or_readme(name: str) -> bool:
    lowered = str(name).strip().lower()
    return "license" in lowered or "licence" in lowered or "readme" in lowered or "copyright" in lowered


def _normalize_extension(value: object) -> str:
    raw = " ".join(str(value or "").split()).strip().lower()
    if not raw:
        return ""
    if not raw.startswith("."):
        raw = f".{raw}"
    return raw


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


if __name__ == "__main__":
    raise SystemExit(main())
