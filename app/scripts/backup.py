"""python -m app.scripts.backup export|verify|restore PATH

RELYQO_BACKUP_PASSPHRASE must be supplied through a secret environment variable.
RELYQO_RESTORE_DATABASE_URL must name a separate EMPTY database for restore.
"""

import argparse
import os
from pathlib import Path
from sqlalchemy import create_engine
from app.backups import create_snapshot, restore_snapshot, unpack_snapshot
from app.config import settings, postgres_url


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["export", "verify", "restore"])
    parser.add_argument("path", type=Path)
    args = parser.parse_args()
    phrase = os.environ.get("RELYQO_BACKUP_PASSPHRASE", "")
    if args.action == "export":
        raw = create_snapshot(create_engine(settings.database_url), phrase)
        descriptor = os.open(args.path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(raw)
        print("Encrypted backup created. Copy it to durable off-site storage.")
    elif args.action == "verify":
        data = unpack_snapshot(args.path.read_bytes(), phrase)
        print(
            f"Archive authenticated; {len(data['tables'])} tables. Perform a restore to verify database consistency."
        )
    else:
        target = postgres_url(os.environ.get("RELYQO_RESTORE_DATABASE_URL", ""))
        if not target or target == settings.database_url:
            raise SystemExit("A separate empty restore database is required")
        result = restore_snapshot(create_engine(target), args.path.read_bytes(), phrase)
        print(f"Restored {result['rows']} rows into the empty test database.")


if __name__ == "__main__":
    main()
