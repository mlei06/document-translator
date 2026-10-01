"""Versioned scrypt password hashes (OWASP N=2**17, r=8, p=1)."""

import hashlib
import hmac
import secrets
import threading

_KDF_SLOTS = threading.BoundedSemaphore(2)


def _derive(password: str, salt: bytes) -> bytes:
    with _KDF_SLOTS:
        return hashlib.scrypt(
            password.encode("utf-8"),
            salt=salt,
            n=2**17,
            r=8,
            p=1,
            maxmem=256 * 1024 * 1024,
            dklen=32,
        )


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    return f"scrypt-v1${salt.hex()}${_derive(password, salt).hex()}"


def verify_password(password: str, encoded: str | None) -> bool:
    # Missing accounts still perform the same expensive derivation.
    salt, expected = b"missing-account!", bytes(32)
    valid_encoding = False
    if encoded is not None:
        try:
            version, salt_hex, digest_hex = encoded.split("$")
            salt, expected = bytes.fromhex(salt_hex), bytes.fromhex(digest_hex)
            valid_encoding = version == "scrypt-v1" and len(salt) == 16 and len(expected) == 32
        except ValueError:
            pass
    actual = _derive(password, salt if valid_encoding else b"missing-account!")
    return hmac.compare_digest(actual, expected) and valid_encoding
