from __future__ import annotations

from pathlib import Path
import subprocess
import sys


def _load_targets(path: Path) -> list[str]:
    if not path.exists():
        raise FileNotFoundError(f"Target file not found: {path}")
    targets: list[str] = []
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = " ".join(raw_line.split()).strip()
        if not line or line.startswith("#"):
            continue
        targets.append(line)
    return targets


def _validate_targets(*, repo_root: Path, targets: list[str]) -> list[str]:
    missing: list[str] = []
    for target in targets:
        if not (repo_root / target).exists():
            missing.append(target)
    return missing


def main() -> int:
    repo_root = Path(__file__).resolve().parents[1]
    targets_file = repo_root / "scripts" / "mypy_targets.txt"
    try:
        targets = _load_targets(targets_file)
    except FileNotFoundError as exc:
        print(str(exc), file=sys.stderr)
        return 2

    if not targets:
        print("No mypy targets configured in scripts/mypy_targets.txt", file=sys.stderr)
        return 2

    missing_targets = _validate_targets(repo_root=repo_root, targets=targets)
    if missing_targets:
        print("These mypy targets do not exist:", file=sys.stderr)
        for item in missing_targets:
            print(f"- {item}", file=sys.stderr)
        return 2

    command = [sys.executable, "-m", "mypy", *targets]
    print("Running:", " ".join(command))
    completed = subprocess.run(command, cwd=repo_root, check=False)
    return int(completed.returncode)


if __name__ == "__main__":
    raise SystemExit(main())
