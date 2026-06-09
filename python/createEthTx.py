import argparse
import hashlib
import hmac
import json
import os
import sys
from pathlib import Path
from Crypto.Hash import keccak as _keccak

sys.path.append(str(Path(__file__).resolve().parent.parent))

from assets.crypto_utils import decrypt_private_key


# ============================================================
# Keccak-256
# ============================================================

def keccak256(data: bytes) -> bytes:
    k = _keccak.new(digest_bits=256)
    k.update(data)
    return k.digest()


# ============================================================
# RFC-6979 deterministic k
# ============================================================

N = 0xFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFEBAAEDCE6AF48A03BBFD25E8CD0364141

def generate_k_rfc6979(priv_int: int, msg_hash_int: int) -> int:
    priv_bytes = priv_int.to_bytes(32, "big")
    msg_bytes  = msg_hash_int.to_bytes(32, "big")

    v = b"\x01" * 32
    k = b"\x00" * 32

    k = hmac.new(k, v + b"\x00" + priv_bytes + msg_bytes, hashlib.sha256).digest()
    v = hmac.new(k, v, hashlib.sha256).digest()
    k = hmac.new(k, v + b"\x01" + priv_bytes + msg_bytes, hashlib.sha256).digest()
    v = hmac.new(k, v, hashlib.sha256).digest()

    while True:
        v = hmac.new(k, v, hashlib.sha256).digest()
        candidate = int.from_bytes(v, "big")
        if 1 <= candidate < N:
            return candidate
        k = hmac.new(k, v + b"\x00", hashlib.sha256).digest()
        v = hmac.new(k, v, hashlib.sha256).digest()


# ============================================================
# secp256k1 scalar multiply  →  R.x mod N
# ============================================================

P = 0xFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFEFFFFFC2F
G = (
    0x79BE667EF9DCBBAC55A06295CE870B07029BFCDB2DCE28D959F2815B16F81798,
    0x483ADA7726A3C4655DA4FBFC0E1108A8FD17B448A68554199C47D08FFB10D4B8,
)

def _point_add(p1, p2):
    if p1 is None: return p2
    if p2 is None: return p1
    x1, y1 = p1
    x2, y2 = p2
    if x1 == x2:
        if y1 != y2: return None
        m = (3 * x1 * x1 * pow(2 * y1, P - 2, P)) % P
    else:
        m = ((y2 - y1) * pow((x2 - x1) % P, P - 2, P)) % P
    x3 = (m * m - x1 - x2) % P
    return (x3, (m * (x1 - x3) - y1) % P)

def _scalar_mult(k: int):
    result, base = None, G
    while k:
        if k & 1: result = _point_add(result, base)
        base = _point_add(base, base)
        k >>= 1
    return result

def get_r_from_k(k: int) -> int:
    return _scalar_mult(k)[0] % N

def pubkey_from_privkey(priv_int: int) -> tuple:
    return _scalar_mult(priv_int)


# ============================================================
# ECDSA sign + encode as (v, r, s)
# ============================================================

def sign_hash(z: int, priv_int: int) -> tuple[int, int, int]:
    k  = generate_k_rfc6979(priv_int, z)
    r  = get_r_from_k(k)
    s  = (pow(k, -1, N) * (z + r * priv_int)) % N
    if s > N // 2:
        s = N - s

    # recovery id (0 or 1)
    point = _scalar_mult(k)
    v = point[1] & 1

    return v, r, s


# ============================================================
# Wallet lookup
# ============================================================

def find_eth_address(address: str, wallet_path: str) -> tuple[str, str]:
    with open(wallet_path) as f:
        data = json.load(f)
    addr_lower = address.lower()
    for obj in data["wallet"]["addresses"]:
        if obj.get("address", "").lower() == addr_lower:
            return obj["private-key-enc"], obj["public-key"]
    raise KeyError(f"Address {address} not found in wallet")


# ============================================================
# RLP (minimal — mirrors createEthTx.py)
# ============================================================

def _int_to_bytes(v: int) -> bytes:
    if v == 0: return b""
    return v.to_bytes((v.bit_length() + 7) // 8, "big")

def rlp_encode(item) -> bytes:
    if isinstance(item, int):
        return rlp_encode(_int_to_bytes(item))
    if isinstance(item, bytes):
        n = len(item)
        if n == 1 and item[0] < 0x80: return item
        if n <= 55: return bytes([0x80 + n]) + item
        lb = _int_to_bytes(n)
        return bytes([0xB7 + len(lb)]) + lb + item
    if isinstance(item, list):
        payload = b"".join(rlp_encode(x) for x in item)
        n = len(payload)
        if n <= 55: return bytes([0xC0 + n]) + payload
        lb = _int_to_bytes(n)
        return bytes([0xF7 + len(lb)]) + lb + payload
    raise TypeError(f"Unsupported RLP type: {type(item)}")


# ============================================================
# Detect tx type and compute signing hash
# ============================================================

def tx_sighash(raw: bytes) -> tuple[int, bytes]:
    """Return (tx_type, hash_to_sign)."""
    if raw[0] == 0x02:
        # EIP-1559 type 2: hash is keccak256(0x02 || rlp(fields))
        return 2, keccak256(raw)

    # Type 0 legacy: strip EIP-155 trailer (chain, 0, 0), re-encode, double-hash
    # The raw bytes ARE the full RLP list — just hash as-is per EIP-155
    return 0, keccak256(raw)


# ============================================================
# Encode signed tx
# ============================================================

def encode_signed_type0(raw_unsigned: bytes, v: int, r: int, s: int, chain_id: int) -> bytes:
    # Decode unsigned RLP list to extract fields
    # Simplest: decode the list payload, strip last 3 (chain,0,0), re-encode with v,r,s
    # Parse outer RLP list manually
    data = raw_unsigned
    assert data[0] >= 0xC0
    if data[0] <= 0xF7:
        payload = data[1:]
    else:
        ll = data[0] - 0xF7
        payload = data[1 + ll:]

    fields = _rlp_decode_list(payload)
    # fields: [nonce, gasprice, gaslimit, to, value, data, chain, 0, 0]
    unsigned_fields = fields[:6]

    eip155_v = v + 35 + 2 * chain_id
    return rlp_encode(unsigned_fields + [eip155_v, r, s])


def encode_signed_type2(raw_unsigned: bytes, v: int, r: int, s: int) -> bytes:
    # Strip 0x02 prefix, decode payload list, append v,r,s
    data = raw_unsigned[1:]
    if data[0] <= 0xF7:
        payload = data[1:]
    else:
        ll = data[0] - 0xF7
        payload = data[1 + ll:]

    fields = _rlp_decode_list(payload)
    # fields: [chain, nonce, maxPriorityFee, maxFee, gasLimit, to, value, data, accessList]
    return b"\x02" + rlp_encode(fields + [v, r, s])


def _rlp_decode_list(payload: bytes) -> list:
    items = []
    offset = 0
    while offset < len(payload):
        b = payload[offset]
        if b < 0x80:
            items.append(payload[offset:offset+1])
            offset += 1
        elif b <= 0xB7:
            n = b - 0x80
            items.append(payload[offset+1:offset+1+n])
            offset += 1 + n
        elif b <= 0xBF:
            ll = b - 0xB7
            n = int.from_bytes(payload[offset+1:offset+1+ll], "big")
            items.append(payload[offset+1+ll:offset+1+ll+n])
            offset += 1 + ll + n
        elif b <= 0xF7:
            n = b - 0xC0
            items.append(payload[offset:offset+1+n])
            offset += 1 + n
        else:
            ll = b - 0xF7
            n = int.from_bytes(payload[offset+1:offset+1+ll], "big")
            items.append(payload[offset:offset+1+ll+n])
            offset += 1 + ll + n
    return items


# ============================================================
# Main signer
# ============================================================

def sign_transaction(raw_hex: str, wallet_name: str, password: str, from_address: str) -> str:
    raw = bytes.fromhex(raw_hex)
    tx_type, z_bytes = tx_sighash(raw)
    z = int.from_bytes(z_bytes, "big")

    wallet_path = os.path.join("..", "wallets", wallet_name + ".json")
    priv_enc, _ = find_eth_address(from_address, wallet_path)
    priv_int = int(decrypt_private_key(bytes.fromhex(priv_enc), password).hex(), 16)

    # Extract chain_id for type 0 EIP-155 v calculation
    chain_id = 1
    if tx_type == 0:
        data = raw
        if data[0] <= 0xF7:
            payload = data[1:]
        else:
            ll = data[0] - 0xF7
            payload = data[1 + ll:]
        fields = _rlp_decode_list(payload)
        if len(fields) >= 7:
            chain_id = int.from_bytes(fields[6], "big") if fields[6] else 1

    v, r, s = sign_hash(z, priv_int)
    print(f"  v={v}  r={hex(r)}  s={hex(s)}")

    if tx_type == 0:
        signed = encode_signed_type0(raw, v, r, s, chain_id)
    else:
        signed = encode_signed_type2(raw, v, r, s)

    return signed.hex()


# ============================================================
# CLI
# ============================================================

def _parse_args():
    parser = argparse.ArgumentParser(description="Sign an unsigned Ethereum transaction")
    parser.add_argument("transaction", help="Unsigned raw tx hex")
    parser.add_argument("name", help="Wallet name")
    parser.add_argument("-f", "--from", dest="from_address", required=True, help="Sender address (0x...)")
    parser.add_argument("-p", "--password", required=True, help="Wallet decryption password")
    return parser.parse_args()


def main():
    args = _parse_args()
    print("--- CONFIG ---")
    print(f"  Wallet  : {args.name}")
    print(f"  From    : {args.from_address}")
    signed = sign_transaction(args.transaction, args.name, args.password, args.from_address)
    print("--- SIGNED TX ---")
    print(signed)


if __name__ == "__main__":
    main()
