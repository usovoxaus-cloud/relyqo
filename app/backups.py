"""Portable encrypted snapshots. Restore only into an empty, separate database."""

import base64
from datetime import datetime
import gzip
import json
import os

from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.scrypt import Scrypt
from sqlalchemy import MetaData, select, text

MAGIC = b"RELYQO-BACKUP-1\n"
LIMIT = 64 * 1024 * 1024


def encode(value):
    if isinstance(value, bytes):
        return {"$bytes": base64.b64encode(value).decode()}
    if isinstance(value, datetime):
        return {"$datetime": value.isoformat()}
    raise TypeError("Unsupported backup value")


def decode(value):
    if set(value) == {"$bytes"}:
        return base64.b64decode(value["$bytes"], validate=True)
    if set(value) == {"$datetime"}:
        return datetime.fromisoformat(value["$datetime"])
    return value


def key(passphrase, salt):
    if not 16 <= len(passphrase) <= 200:
        raise ValueError("Backup passphrase must contain 16–200 characters")
    return Scrypt(salt=salt, length=32, n=2**15, r=8, p=1).derive(passphrase.encode())


def create_snapshot(engine, passphrase):
    # One repeatable-read transaction avoids a mixed snapshot when ratings arrive during export.
    with engine.connect().execution_options(
        isolation_level="REPEATABLE READ"
        if engine.dialect.name == "postgresql"
        else "SERIALIZABLE"
    ) as connection:
        with connection.begin():
            if engine.dialect.name == "postgresql":
                connection.execute(text("SET TRANSACTION READ ONLY"))
            metadata = MetaData()
            metadata.reflect(connection)
            tables = {}
            size = 0
            for table in metadata.sorted_tables:
                rows = []
                for row in connection.execute(select(table)).mappings():
                    data = dict(row)
                    size += len(json.dumps(data, default=encode))
                    if size > LIMIT:
                        raise ValueError("Use pg_dump for databases larger than 64 MB")
                    rows.append(data)
                tables[table.name] = rows
            payload = json.dumps(
                {
                    "format": 1,
                    "created_at": datetime.utcnow().isoformat(),
                    "tables": tables,
                },
                default=encode,
            ).encode()
    salt, nonce = os.urandom(16), os.urandom(12)
    encrypted = AESGCM(key(passphrase, salt)).encrypt(
        nonce, gzip.compress(payload), MAGIC
    )
    return MAGIC + salt + nonce + encrypted


def unpack_snapshot(raw, passphrase):
    if not raw.startswith(MAGIC) or len(raw) > LIMIT + 1024:
        raise ValueError("Invalid backup format")
    offset = len(MAGIC)
    plain = AESGCM(key(passphrase, raw[offset : offset + 16])).decrypt(
        raw[offset + 16 : offset + 28], raw[offset + 28 :], MAGIC
    )
    from io import BytesIO

    with gzip.GzipFile(fileobj=BytesIO(plain)) as stream:
        payload = stream.read(LIMIT + 1)
    if len(payload) > LIMIT:
        raise ValueError("Backup exceeds maximum size")
    data = json.loads(payload, object_hook=decode)
    if data.get("format") != 1 or not isinstance(data.get("tables"), dict):
        raise ValueError("Invalid backup manifest")
    return data


def restore_snapshot(engine, raw, passphrase):
    from .db import Base
    from . import models  # noqa: F401

    data = unpack_snapshot(raw, passphrase)
    metadata = MetaData()
    with engine.begin() as connection:
        metadata.reflect(connection)
        for table in metadata.tables.values():
            if connection.execute(select(table).limit(1)).first():
                raise ValueError(
                    "Restore requires an empty database; existing data must never be overwritten"
                )
        # Restrict restoration to the known schema, never execute statements from the backup.
        unknown = set(data["tables"]) - set(Base.metadata.tables) - {"alembic_version"}
        if unknown:
            raise ValueError("Unknown tables in backup")
        Base.metadata.create_all(connection)
        for table in Base.metadata.sorted_tables:
            for row in data["tables"].get(table.name, []):
                if set(row) - set(table.columns.keys()):
                    raise ValueError("Backup schema is newer than this application")
                connection.execute(table.insert().values(**row))
        versions = data["tables"].get("alembic_version", [])
        if versions:
            connection.execute(
                text(
                    "CREATE TABLE IF NOT EXISTS alembic_version (version_num VARCHAR(32) NOT NULL PRIMARY KEY)"
                )
            )
            for row in versions:
                connection.execute(
                    text("INSERT INTO alembic_version (version_num) VALUES (:version)"),
                    {"version": row["version_num"]},
                )
    return {
        "tables": len(data["tables"]),
        "rows": sum(map(len, data["tables"].values())),
        "created_at": data["created_at"],
    }
