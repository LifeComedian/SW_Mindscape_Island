"""SQLite online backup and integrity check. Never overwrites a destination."""
import argparse
from contextlib import closing
from pathlib import Path
import sqlite3


def verify(path):
    with closing(sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True)) as db:
        result = db.execute("PRAGMA integrity_check").fetchall()
        if result != [("ok",)]:
            raise RuntimeError("SQLite integrity check failed")
        if db.execute("PRAGMA foreign_key_check").fetchall():
            raise RuntimeError("SQLite foreign key check failed")


def backup(source, destination):
    source, destination = Path(source), Path(destination)
    if not source.is_file() or destination.exists() or source.resolve() == destination.resolve():
        raise ValueError("Need an existing source and a new, distinct destination")
    with closing(sqlite3.connect(source.resolve().as_uri() + "?mode=ro", uri=True)) as src:
        with closing(sqlite3.connect(destination)) as dst:
            src.backup(dst)
    verify(destination)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("operation", choices=("backup", "verify"))
    parser.add_argument("source", type=Path)
    parser.add_argument("destination", type=Path, nargs="?")
    args = parser.parse_args()
    if args.operation == "backup":
        if args.destination is None:
            parser.error("backup requires a destination")
        backup(args.source, args.destination)
    else:
        verify(args.source)
    print("SQLite backup/integrity check passed")
