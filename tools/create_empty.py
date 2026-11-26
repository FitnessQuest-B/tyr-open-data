"""Create an empty TYR Open Data or Brain Lab file from versioned SQL."""

import argparse
import os
import sqlite3
import sys
import tempfile
from pathlib import Path

from schema_support import check_empty, clean_connect, load_contract


def create_empty(kind, destination, *, version=None):
    folder, contract = load_contract(version)
    artifact = contract["artifacts"][kind]
    ddl = (folder / artifact["sql"]).read_text()
    destination = Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=destination.parent) as job:
        pending = Path(job) / "clean.sqlite"
        with clean_connect(pending) as db:
            db.execute("PRAGMA journal_mode=DELETE")
            db.execute("PRAGMA page_size=4096")
            db.execute("PRAGMA foreign_keys=ON")
            db.executescript(ddl)
            check_empty(db, artifact)
        # Publish only the checked file and refuse collisions, including symlinks.
        os.link(pending, destination)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("kind", choices=["records", "brain-lab"])
    parser.add_argument("destination", type=Path)
    args = parser.parse_args()
    try:
        create_empty(args.kind, args.destination)
    except (OSError, ValueError, sqlite3.Error) as error:
        parser.exit(1, f"{error}\n")


if __name__ == "__main__":
    sys.exit(main())
