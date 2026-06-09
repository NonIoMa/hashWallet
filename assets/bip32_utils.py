"""Shared BIP32 key derivation utilities for hash-wallet.

Provides path parsing, child key derivation (hardened and normal), full path
traversal from a master key, and compressed public key generation. Used by
makeparent.py and makeaddress.py.
"""

"""Shared BIP32 utilities for hash-wallet."""

import hmac
import hashlib

from ecdsa import SECP256k1, SigningKey
from ecdsa.util import number_to_string


def parse_index(component: str) -> int | None:
    """Convert a path component (e.g. "44'" or "0") into an integer index.

    Returns None for 'm' or empty string.
    Raises ValueError for invalid components.
    """
    if component in ('m', '', None):
        return None

    hardened = component.endswith("'")
    num_str = component[:-1] if hardened else component

    try:
        idx = int(num_str)
    except ValueError:
        raise ValueError(f"Invalid path component: {component}")

    if not (0 <= idx < 0x80000000):
        raise ValueError(f"Index out of range: {idx}")

    if hardened:
        idx |= 0x80000000

    return idx


def derive_child_private_key(parent_privkey: bytes, parent_chaincode: bytes, index: int) -> tuple[bytes, bytes]:
    """Derive a single BIP32 child private key.

    ``index`` may be hardened (>= 0x80000000) or normal.
    Returns a tuple ``(child_privkey, child_chaincode)``.
    """
    if index >= 0x80000000:
        data = b'\x00' + parent_privkey + index.to_bytes(4, 'big')
    else:
        sk = SigningKey.from_string(parent_privkey, curve=SECP256k1)
        vk = sk.get_verifying_key()
        x = number_to_string(vk.pubkey.point.x(), SECP256k1.order)
        prefix = b'\x02' if vk.pubkey.point.y() % 2 == 0 else b'\x03'
        data = prefix + x + index.to_bytes(4, 'big')

    I = hmac.new(parent_chaincode, data, hashlib.sha512).digest()
    IL = I[:32]
    IR = I[32:]

    IL_int = int.from_bytes(IL, 'big')
    parent_int = int.from_bytes(parent_privkey, 'big')
    order = SECP256k1.order

    if IL_int >= order:
        raise ValueError("Invalid IL: derived key out of range")

    child_int = (IL_int + parent_int) % order

    if child_int == 0:
        raise ValueError("Invalid child key: result is zero")

    child_privkey = child_int.to_bytes(32, 'big')
    return child_privkey, IR


def derive_path(master_priv: bytes, master_chaincode: bytes, path: str) -> tuple[bytes, bytes]:
    """Derive a child private key and chaincode from a master key using a BIP32 path.

    Returns a tuple ``(child_privkey, child_chaincode)``.
    Raises ValueError for invalid paths.
    """
    if not path.startswith('m/') and path != 'm':
        raise ValueError("Path must start with 'm/' or be 'm'")

    components = path.split('/')
    if components[0] != 'm':
        raise ValueError("Path must start with 'm'")

    priv = master_priv
    chaincode = master_chaincode

    for comp in components[1:]:
        idx = parse_index(comp)
        if idx is None:
            raise ValueError(f"Invalid path component: {comp}")
        priv, chaincode = derive_child_private_key(priv, chaincode, idx)

    return priv, chaincode


def private_key_to_public_key(privkey: bytes) -> bytes:
    """Convert a private key to a compressed public key."""
    sk = SigningKey.from_string(privkey, curve=SECP256k1)
    vk = sk.get_verifying_key()
    x = number_to_string(vk.pubkey.point.x(), SECP256k1.order)
    prefix = b'\x02' if vk.pubkey.point.y() % 2 == 0 else b'\x03'
    return prefix + x
