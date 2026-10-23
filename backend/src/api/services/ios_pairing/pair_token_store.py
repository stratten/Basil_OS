from __future__ import annotations

import secrets
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional


@dataclass(frozen=True)
class PairingSecret:
    pairing_id: str
    secret: str
    expires_at: datetime


@dataclass(frozen=True)
class PairToken:
    device_id: str
    device_name: str
    token: str
    issued_at: datetime


class PairTokenStore:
    """SQLite-backed store for short-lived pairing secrets and paired device tokens."""

    def __init__(self, database_path: Path):
        self.database_path = database_path
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize_schema()

    def create_pairing_secret(self, ttl_seconds: int = 300) -> PairingSecret:
        pairing_id = secrets.token_urlsafe(18)
        secret = secrets.token_urlsafe(32)
        expires_at = datetime.now(timezone.utc) + timedelta(seconds=ttl_seconds)

        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO pairing_secrets(pairing_id, secret, expires_at)
                VALUES (?, ?, ?)
                """,
                (pairing_id, secret, expires_at.isoformat()),
            )

        return PairingSecret(pairing_id=pairing_id, secret=secret, expires_at=expires_at)

    def complete_pairing(self, pairing_id: str, secret: str, device_id: str, device_name: str) -> Optional[PairToken]:
        now = datetime.now(timezone.utc)
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT secret, expires_at
                FROM pairing_secrets
                WHERE pairing_id = ?
                """,
                (pairing_id,),
            ).fetchone()

            if row is None or row["secret"] != secret:
                return None

            expires_at = datetime.fromisoformat(row["expires_at"])
            if expires_at < now:
                connection.execute("DELETE FROM pairing_secrets WHERE pairing_id = ?", (pairing_id,))
                return None

            token = secrets.token_urlsafe(48)
            connection.execute("DELETE FROM pairing_secrets WHERE pairing_id = ?", (pairing_id,))
            connection.execute(
                """
                INSERT OR REPLACE INTO paired_devices(device_id, device_name, token, issued_at, revoked_at)
                VALUES (?, ?, ?, ?, NULL)
                """,
                (device_id, device_name, token, now.isoformat()),
            )

        return PairToken(device_id=device_id, device_name=device_name, token=token, issued_at=now)

    def validate_token(self, token: str) -> bool:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT device_id
                FROM paired_devices
                WHERE token = ? AND revoked_at IS NULL
                """,
                (token,),
            ).fetchone()
        return row is not None

    def revoke_device(self, device_id: str) -> bool:
        now = datetime.now(timezone.utc).isoformat()
        with self._connect() as connection:
            cursor = connection.execute(
                """
                UPDATE paired_devices
                SET revoked_at = ?
                WHERE device_id = ? AND revoked_at IS NULL
                """,
                (now, device_id),
            )
        return cursor.rowcount > 0

    def list_devices(self) -> list[dict[str, str]]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT device_id, device_name, issued_at
                FROM paired_devices
                WHERE revoked_at IS NULL
                ORDER BY issued_at DESC
                """
            ).fetchall()
        return [dict(row) for row in rows]

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.database_path)
        connection.row_factory = sqlite3.Row
        return connection

    def _initialize_schema(self) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS pairing_secrets (
                    pairing_id TEXT PRIMARY KEY,
                    secret TEXT NOT NULL,
                    expires_at TEXT NOT NULL
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS paired_devices (
                    device_id TEXT PRIMARY KEY,
                    device_name TEXT NOT NULL,
                    token TEXT NOT NULL UNIQUE,
                    issued_at TEXT NOT NULL,
                    revoked_at TEXT
                )
                """
            )

