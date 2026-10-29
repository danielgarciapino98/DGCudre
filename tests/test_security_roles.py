import sqlite3
import unittest

from auth import hash_password
from security_roles import (
    authenticate_user,
    create_user,
    ensure_security_schema,
    has_permission,
    issue_password_reset_token,
    reset_password,
)


class SecurityRolesTests(unittest.TestCase):
    def setUp(self):
        self.conn = sqlite3.connect(":memory:")
        self.conn.execute("""
            CREATE TABLE administrators (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT NOT NULL UNIQUE,
                password_salt TEXT NOT NULL,
                password_hash TEXT NOT NULL
            )
        """)
        salt, digest = hash_password("Owner-password-123")
        self.conn.execute(
            "INSERT INTO administrators(username,password_salt,password_hash) VALUES(?,?,?)",
            ("owner", salt, digest),
        )
        self.conn.commit()
        ensure_security_schema(self.conn)

    def tearDown(self):
        self.conn.close()

    def test_legacy_admin_migrates_as_owner_without_changing_hash(self):
        user = authenticate_user(self.conn, "OWNER", "Owner-password-123")
        self.assertIsNotNone(user)
        self.assertEqual(user["role"], "owner")
        self.assertIsNone(user["point_id"])

    def test_permissions_are_role_limited(self):
        seller = {
            "id": 7, "username": "seller", "role": "seller", "point_id": 1
        }
        self.assertTrue(has_permission(seller, "sales.create_point"))
        self.assertFalse(has_permission(seller, "ai.ask"))
        self.assertFalse(has_permission(seller, "users.manage"))

    def test_operational_user_requires_point_assignment(self):
        with self.assertRaises(ValueError):
            create_user(self.conn, "seller01", "Seller-password-123", "seller")

    def test_password_reset_token_is_single_use(self):
        user = authenticate_user(self.conn, "owner", "Owner-password-123")
        token = issue_password_reset_token(self.conn, user["id"])
        self.assertTrue(reset_password(self.conn, token, "New-owner-password-123"))
        self.assertFalse(reset_password(self.conn, token, "Another-password-123"))
        self.assertIsNone(authenticate_user(self.conn, "owner", "Owner-password-123"))
        self.assertIsNotNone(authenticate_user(self.conn, "owner", "New-owner-password-123"))


if __name__ == "__main__":
    unittest.main()
