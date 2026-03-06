from __future__ import annotations

from hashlib import sha256
from pathlib import Path


class CartoonFlatAssetCatalogService:
    TEMPLATE_DIRS: dict[str, tuple[str, ...]] = {
        "bust": ("Templates", "Bust"),
        "standing": ("Templates", "Standing"),
        "sitting": ("Templates", "Sitting"),
    }
    ATOM_DIRS: dict[str, tuple[str, ...]] = {
        "face": ("Separate Atoms", "face"),
        "head": ("Separate Atoms", "head"),
        "body": ("Separate Atoms", "body"),
        "pose_standing": ("Separate Atoms", "pose", "standing"),
        "pose_sitting": ("Separate Atoms", "pose", "sitting"),
        "accessories": ("Separate Atoms", "accessories"),
        "facial_hair": ("Separate Atoms", "facial-hair"),
    }
    EMOTION_KEYS: tuple[str, ...] = ("neutral", "energetic", "tense", "warm", "inspiring")
    VISEME_KEYS: tuple[str, ...] = ("A", "B", "C", "D", "E", "F", "G", "H", "X")

    _EMOTION_KEYWORDS: dict[str, tuple[str, ...]] = {
        "neutral": ("calm", "blank", "smile", "serious", "solemn"),
        "energetic": ("awe", "driven", "cheeky", "smile", "cute"),
        "tense": ("angry", "fear", "concerned", "rage", "suspic"),
        "warm": ("loving", "smile", "calm", "cute"),
        "inspiring": ("driven", "awe", "smile", "contempl"),
    }
    _VISEME_KEYWORDS: dict[str, tuple[str, ...]] = {
        "A": ("awe", "open", "smile"),
        "B": ("blank", "calm", "serious"),
        "C": ("concerned", "contempt"),
        "D": ("driven", "serious"),
        "E": ("smile", "cute"),
        "F": ("fear", "suspic"),
        "G": ("rage", "angry"),
        "H": ("hectic", "old"),
        "X": ("blank", "calm", "solemn"),
    }

    def __init__(self, *, pack_root: Path) -> None:
        self._pack_root = pack_root
        self._templates: dict[str, list[Path]] = {}
        self._atoms: dict[str, list[Path]] = {}
        self._loaded = False

    def ensure_loaded(self) -> None:
        if self._loaded:
            return
        self._templates = {
            key: self._list_files(*parts, suffixes=(".png",))
            for key, parts in self.TEMPLATE_DIRS.items()
        }
        self._atoms = {
            key: self._list_files(*parts, suffixes=(".svg", ".png"))
            for key, parts in self.ATOM_DIRS.items()
        }
        self._loaded = True

    def summary(self) -> dict[str, object]:
        self.ensure_loaded()
        template_counts = {key: len(paths) for key, paths in self._templates.items()}
        atom_counts = {key: len(paths) for key, paths in self._atoms.items()}
        return {
            "pack_root": str(self._pack_root),
            "template_counts": template_counts,
            "atom_counts": atom_counts,
            "template_total": sum(template_counts.values()),
            "atom_total": sum(atom_counts.values()),
        }

    def profile_for_character(self, *, character_id: str) -> dict[str, object]:
        self.ensure_loaded()
        char_key = _clean(character_id).lower() or "character"
        seed = _stable_seed(char_key)

        standing_templates = self._templates.get("standing", [])
        sitting_templates = self._templates.get("sitting", [])
        bust_templates = self._templates.get("bust", [])
        face_atoms = self._atoms.get("face", [])

        emotion_faces = {
            emotion: self._pick_by_keywords(
                paths=face_atoms,
                keywords=self._EMOTION_KEYWORDS.get(emotion, ()),
                salt=f"{char_key}:{emotion}",
            )
            for emotion in self.EMOTION_KEYS
        }
        viseme_faces = {
            viseme: self._pick_by_keywords(
                paths=face_atoms,
                keywords=self._VISEME_KEYWORDS.get(viseme, ()),
                salt=f"{char_key}:viseme:{viseme}",
            )
            for viseme in self.VISEME_KEYS
        }
        blink_face = self._pick_by_keywords(
            paths=face_atoms,
            keywords=("closed", "blank", "calm"),
            salt=f"{char_key}:blink",
        )

        return {
            "character_id": char_key,
            "templates": {
                "standing": self._choose_one(standing_templates, salt=f"{char_key}:standing"),
                "sitting": self._choose_one(sitting_templates, salt=f"{char_key}:sitting"),
                "bust": self._choose_one(bust_templates, salt=f"{char_key}:bust"),
            },
            "template_alternates": {
                "standing": self._choose_many(standing_templates, count=4, salt=f"{char_key}:standing:alts"),
                "sitting": self._choose_many(sitting_templates, count=3, salt=f"{char_key}:sitting:alts"),
                "bust": self._choose_many(bust_templates, count=3, salt=f"{char_key}:bust:alts"),
            },
            "emotion_faces": emotion_faces,
            "viseme_faces": viseme_faces,
            "blink_face": blink_face,
            "head_overlay": self._choose_one(self._atoms.get("head", []), salt=f"{char_key}:head"),
            "body_overlay": self._choose_one(self._atoms.get("body", []), salt=f"{char_key}:body"),
            "accessory_overlay": self._choose_one(self._atoms.get("accessories", []), salt=f"{char_key}:accessory"),
            "facial_hair_overlay": self._choose_one(self._atoms.get("facial_hair", []), salt=f"{char_key}:facial_hair"),
            "pose_standing": self._choose_many(self._atoms.get("pose_standing", []), count=6, salt=f"{char_key}:pose:standing"),
            "pose_sitting": self._choose_many(self._atoms.get("pose_sitting", []), count=4, salt=f"{char_key}:pose:sitting"),
            "seed": seed,
        }

    def _list_files(self, *parts: str, suffixes: tuple[str, ...]) -> list[Path]:
        root = self._pack_root.joinpath(*parts)
        if not root.exists() or not root.is_dir():
            return []
        return sorted(
            [
                path
                for path in root.iterdir()
                if path.is_file() and path.suffix.lower() in suffixes
            ],
            key=lambda item: item.name.lower(),
        )

    def _pick_by_keywords(self, *, paths: list[Path], keywords: tuple[str, ...], salt: str) -> Path | None:
        if not paths:
            return None
        lowered_keywords = tuple(_clean(keyword).lower() for keyword in keywords if _clean(keyword))
        if lowered_keywords:
            filtered = [
                path
                for path in paths
                if any(keyword in path.stem.lower() for keyword in lowered_keywords)
            ]
            if filtered:
                return self._choose_one(filtered, salt=salt)
        return self._choose_one(paths, salt=salt)

    def _choose_one(self, paths: list[Path], *, salt: str) -> Path | None:
        if not paths:
            return None
        idx = _stable_seed(salt) % len(paths)
        return paths[idx]

    def _choose_many(self, paths: list[Path], *, count: int, salt: str) -> list[Path]:
        if not paths:
            return []
        requested = max(1, min(int(count), len(paths)))
        start = _stable_seed(salt) % len(paths)
        rotated = paths[start:] + paths[:start]
        return rotated[:requested]


def _stable_seed(value: str) -> int:
    encoded = value.encode("utf-8", errors="ignore")
    digest = sha256(encoded).digest()
    return int.from_bytes(digest[:8], byteorder="big", signed=False)


def _clean(value: object) -> str:
    return " ".join(str(value or "").split()).strip()
