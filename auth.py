"""Administrator password hashing helpers."""
import hashlib
import hmac
import secrets

PASSWORD_SCRYPT_N = 2**14


def hash_password(password):
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(
        password.encode("utf-8"), salt=salt, n=PASSWORD_SCRYPT_N, r=8, p=1
    )
    return salt.hex(), digest.hex()


def verify_password(password, salt_hex, digest_hex):
    try:
        salt = bytes.fromhex(salt_hex)
        expected = bytes.fromhex(digest_hex)
    except ValueError:
        return False
    actual = hashlib.scrypt(
        password.encode("utf-8"), salt=salt, n=PASSWORD_SCRYPT_N, r=8, p=1
    )
    return hmac.compare_digest(actual, expected)
