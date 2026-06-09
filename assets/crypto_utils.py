"""Encryption utilities for hash-wallet private key storage.

Provides AES-256-GCM encryption and decryption of private keys using a
password-derived key (PBKDF2-SHA256, 200 000 iterations). The encrypted
format is: version (1 byte) || salt (16 bytes) || nonce (12 bytes) || ciphertext.
Backward-compatible with the old format (no version byte).
"""

import os

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
from cryptography.hazmat.primitives.ciphers.aead import AESGCM


def _derive_key(password: str, salt: bytes) -> bytes:
    """Derive a 256-bit key from a password using PBKDF2 (SHA-256)."""
    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=32,
        salt=salt,
        iterations=200_000,
    )
    return kdf.derive(password.encode('utf-8'))


def encrypt_private_key(private_key: bytes, password: str) -> bytes:
    """Encrypt a 32-byte private key with a password.

    The returned value consists of:
        version (1 byte) || salt (16 bytes) || nonce (12 bytes) || ciphertext
    """
    if not isinstance(private_key, (bytes, bytearray)):
        raise TypeError("private_key must be bytes")

    salt = os.urandom(16)
    key = _derive_key(password, salt)
    aesgcm = AESGCM(key)
    nonce = os.urandom(12)
    ciphertext = aesgcm.encrypt(nonce, private_key, associated_data=None)

    # Version byte 1: [0x01] || salt || nonce || ciphertext
    return b"\x01" + salt + nonce + ciphertext


def decrypt_private_key(encrypted: bytes, password: str) -> bytes:
    """Decrypt data produced by :func:`encrypt_private_key`.

    Raises ``cryptography.exceptions.InvalidTag`` if the password is
    incorrect or the ciphertext was tampered with.
    """
    if not isinstance(encrypted, (bytes, bytearray)):
        raise TypeError("encrypted data must be bytes")
    if len(encrypted) < 1 + 16 + 12:
        raise ValueError("encrypted data is too short")

    version = encrypted[0]
    if version == 1:
        salt = encrypted[1:17]
        nonce = encrypted[17:29]
        ciphertext = encrypted[29:]
    else:
        # Backward-compatibility with old format (no version byte)
        salt = encrypted[:16]
        nonce = encrypted[16:28]
        ciphertext = encrypted[28:]

    key = _derive_key(password, salt)
    aesgcm = AESGCM(key)
    return aesgcm.decrypt(nonce, ciphertext, associated_data=None)
