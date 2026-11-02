"""Check release files against the SHA-256 manifest."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
import sys


MANIFEST = "FILE_MANIFEST.json"
LOCAL_ARTIFACTS = {"node_modules", ".next", "__pycache__", ".venv", "venv"}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--strict", action="store_true", help="Reject all unlisted files, including build caches.")
    args = parser.parse_args()
    root = args.root.resolve()
    errors: list[str] = []
    seen: set[str] = set()
    folded: set[str] = set()
    try:
        data = json.loads((root / MANIFEST).read_text(encoding="utf-8"))
        entries = data["files"]
        if data["schema_version"] != 1 or len(entries) != data["listed_files"]:
            raise ValueError("Manifest schema/count mismatch")
        for entry in entries:
            name = entry["path"]
            rel = PurePosixPath(name)
            if (not name or "\\" in name or ":" in name or rel.is_absolute()
                    or ".." in rel.parts or rel.as_posix() != name
                    or name == MANIFEST or name.casefold() in folded):
                raise ValueError("Invalid or duplicate manifest path: " + name)
            seen.add(name)
            folded.add(name.casefold())
            target = root.joinpath(*rel.parts)
            if not target.resolve().is_relative_to(root) or any(
                    root.joinpath(*rel.parts[:i]).is_symlink() for i in range(1, len(rel.parts) + 1)):
                errors.append("Linked/outside path: " + name)
            elif not target.is_file():
                errors.append("Missing: " + name)
            elif target.stat().st_size != entry["bytes"] or sha256(target) != entry["sha256"]:
                errors.append("Changed: " + name)
        expected = seen | {MANIFEST}
        ignored = 0
        for target in root.rglob("*"):
            rel = target.relative_to(root)
            if ".git" in rel.parts:
                continue
            if target.is_symlink():
                errors.append("Symlink in release tree: " + rel.as_posix())
                continue
            if not target.is_file() or rel.as_posix() in expected:
                continue
            if not args.strict and any(part in LOCAL_ARTIFACTS for part in rel.parts):
                ignored += 1
                continue
            errors.append("Unlisted: " + rel.as_posix())
        if data["total_release_files"] != len(expected):
            errors.append("Total release file count does not match the manifest")
    except (OSError, ValueError, KeyError, TypeError) as exc:
        print("Verification failed: " + str(exc), file=sys.stderr)
        return 2
    if errors:
        print("Verification failed:", file=sys.stderr)
        for error in errors:
            print("- " + error, file=sys.stderr)
        return 1
    print(f"PASS: {len(seen)} file hashes match; {len(expected)} release files including the manifest.")
    if ignored:
        print(f"Ignored {ignored} local build/cache files. Use --strict on the directory to be published.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
