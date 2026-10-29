"""Additive role-based authentication primitives for DGCuadres/POS.

This module deliberately does not replace the legacy administrators table. Run
ensure_security_schema() on the application's existing SQLite connection before
wiring these helpers into web routes. Password-reset tokens are single-use,
stored only as SHA-256 hashes, and must be delivered through a trusted channel.
"""
from __future__ import annotations

import hashlib
import secrets
import sqlite3
from datetime import datetime, timedelta, timezone
from typing import Optional

from auth import hash_password, verify_password

ROLES = {"owner", "administrator", "seller", "storekeeper"}

# Authorization is enforced server-side; hiding a button in the UI is not enough.
ROLE_PERMISSIONS = {
    "owner": frozenset({
        "dashboard.read_all", "sales.read_all", "sales.create_all",
        "inventory.read_all", "inventory.receive", "inventory.transfer",
        "shifts.read_all", "shifts.count", "shifts.close",
        "shifts.approve_difference", "users.manage", "settings.manage",
        "ai.ask", "reports.read_all",
    }),
    "administrator": frozenset({
        "dashboard.read_point", "sales.read_point", "inventory.read_point",
        "shifts.read_point", "shifts.count", "shifts.close",
        "reports.read_point", "inventory.count",
    }),
    "seller": frozenset({"sales.read_point", "sales.create_point"}),
    "storekeeper": frozenset({
        "inventory.read_assigned", "inventory.receive", "inventory.transfer",
    }),
}


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _token_digest(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def ensure_security_schema(conn: sqlite3.Connection) -> None:
    """Create role/reset tables and migrate existing administrators as owners.

    Safe to call repeatedly. Existing administrator credentials are copied as
    hashes; plaintext passwords are never created or stored.
    """
    conn.execute("""
        CREATE TABLE IF NOT EXISTS app_users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT NOT NULL UNIQUE COLLATE NOCASE,
            password_salt TEXT NOT NULL,
            password_hash TEXT NOT NULL,
            role TEXT NOT NULL CHECK(role IN
                ('owner','administrator','seller','storekeeper')),
            point_id INTEGER,
            active INTEGER NOT NULL DEFAULT 1 CHECK(active IN (0,1)),
            created_at TEXT NOT NULL DEFAULT (datetime('now')),
            updated_at TEXT NOT NULL DEFAULT (datetime('now'))
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS password_reset_tokens (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL REFERENCES app_users(id) ON DELETE CASCADE,
            token_hash TEXT NOT NULL UNIQUE,
            expires_at TEXT NOT NULL,
            used_at TEXT,
            created_at TEXT NOT NULL DEFAULT (datetime('now'))
        )
    """)
    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_password_reset_user
        ON password_reset_tokens(user_id, expires_at)
    """)
    # One-time migration. The old admin becomes the owner; don't silently
    # promote any subsequently-created administrator accounts.
    legacy = conn.execute("""
        SELECT username, password_salt, password_hash
        FROM administrators ORDER BY id
    """).fetchall()
    for row in legacy:
        username, salt, digest = row[0], row[1], row[2]
        exists = conn.execute(
            "SELECT 1 FROM app_users WHERE username = ? COLLATE NOCASE",
            (username,),
        ).fetchone()
        if not exists:
            conn.execute("""
                INSERT INTO app_users
                    (username, password_salt, password_hash, role)
                VALUES (?, ?, ?, 'owner')
            """, (username, salt, digest))
    conn.commit()


def create_user(
    conn: sqlite3.Connection,
    username: str,
    password: str,
    role: str,
    point_id: Optional[int] = None,
) -> int:
    username = username.strip().casefold()
    if role not in ROLES:
        raise ValueError("Rol no válido.")
    if len(username) < 3 or len(username) > 100:
        raise ValueError("El usuario debe tener entre 3 y 100 caracteres.")
    if len(password) < 10 or len(password) > 1024:
        raise ValueError("La contraseña debe tener entre 10 y 1024 caracteres.")
    if role != "owner" and point_id is None:
        raise ValueError("Los usuarios operativos deben tener un punto asignado.")
    salt, digest = hash_password(password)
    cur = conn.execute("""
        INSERT INTO app_users
            (username, password_salt, password_hash, role, point_id)
        VALUES (?, ?, ?, ?, ?)
    """, (username, salt, digest, role, point_id))
    conn.commit()
    return int(cur.lastrowid)


def authenticate_user(
    conn: sqlite3.Connection, username: str, password: str
) -> Optional[dict]:
    username = username.strip().casefold()
    if len(password) > 1024:
        return None
    row = conn.execute("""
        SELECT id, username, password_salt, password_hash, role, point_id, active
        FROM app_users WHERE username = ? COLLATE NOCASE
    """, (username,)).fetchone()
    if row is None:
        # Reduce username-enumeration timing differences.
        verify_password(password, "00" * 16, "00" * 32)
        return None
    if not row[6] or not verify_password(password, row[2], row[3]):
        return None
    return {
        "id": row[0], "username": row[1], "role": row[4],
        "point_id": row[5],
    }


def has_permission(user: dict, permission: str) -> bool:
    role = user.get("role")
    if role not in ROLE_PERMISSIONS:
        return False
    if permission == "ai.ask" and role != "owner":
        return False
    return permission in ROLE_PERMISSIONS[role]


def issue_password_reset_token(
    conn: sqlite3.Connection, user_id: int, ttl_minutes: int = 20
) -> str:
    """Create a single-use reset token; caller must deliver it out-of-band."""
    if not 1 <= ttl_minutes <= 60:
        raise ValueError("La vigencia del enlace debe estar entre 1 y 60 minutos.")
    user = conn.execute(
        "SELECT id, active FROM app_users WHERE id = ?", (user_id,)
    ).fetchone()
    if not user or not user[1]:
        raise ValueError("No existe un usuario activo.")
    token = secrets.token_urlsafe(32)
    expires = (utc_now() + timedelta(minutes=ttl_minutes)).isoformat()
    conn.execute("""
        INSERT INTO password_reset_tokens (user_id, token_hash, expires_at)
        VALUES (?, ?, ?)
    """, (user_id, _token_digest(token), expires))
    conn.commit()
    return token


def reset_password(
    conn: sqlite3.Connection, token: str, new_password: str
) -> bool:
    """Consume a valid reset token and replace the password atomically."""
    if len(new_password) < 10 or len(new_password) > 1024:
        raise ValueError("La contraseña debe tener entre 10 y 1024 caracteres.")
    now = utc_now()
    conn.execute("BEGIN IMMEDIATE")
    try:
        row = conn.execute("""
            SELECT t.id, t.user_id, t.expires_at
            FROM password_reset_tokens t
            JOIN app_users u ON u.id = t.user_id
            WHERE t.token_hash = ? AND t.used_at IS NULL AND u.active = 1
        """, (_token_digest(token),)).fetchone()
        if not row:
            conn.rollback()
            return False
        expiry = datetime.fromisoformat(row[2])
        if expiry.tzinfo is None:
            expiry = expiry.replace(tzinfo=timezone.utc)
        if expiry <= now:
            conn.rollback()
            return False
        salt, digest = hash_password(new_password)
        conn.execute("""
            UPDATE app_users
            SET password_salt = ?, password_hash = ?, updated_at = datetime('now')
            WHERE id = ?
        """, (salt, digest, row[1]))
        conn.execute("""
            UPDATE password_reset_tokens SET used_at = ?
            WHERE id = ? AND used_at IS NULL
        """, (now.isoformat(), row[0]))
        # Revoke all outstanding reset tokens for this account.
        conn.execute("""
            UPDATE password_reset_tokens SET used_at = ?
            WHERE user_id = ? AND used_at IS NULL
        """, (now.isoformat(), row[1]))
        conn.commit()
        return True
    except Exception:
        conn.rollback()
        raise
