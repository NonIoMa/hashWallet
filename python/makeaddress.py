"""Address derivation utility for hash-wallet.

This tool reads the master key from an existing wallet JSON file, decrypts
it with a password, derives a child private key using the supplied BIP32
path, and appends an address entry to the wallet. Each derived key is
encrypted with a second password.
"""

import argparse
import os
import json
import hmac
import hashlib
import sys
from pathlib import Path

import base58
from bech32 import bech32_encode, convertbits
from ecdsa import SECP256k1, SigningKey
from ecdsa.util import number_to_string

sys.path.append(str(Path(__file__).resolve().parent.parent))

from assets.crypto_utils import encrypt_private_key, decrypt_private_key
from assets.bip32_utils import derive_path, parse_index, private_key_to_public_key


def hash160(data: bytes) -> bytes:
    return hashlib.new('ripemd160', hashlib.sha256(data).digest()).digest()


def cashaddr_polymod(values):
    """CashAddr checksum polymod calculation."""
    c = 1
    for value in values:
        c0 = c >> 35
        c = ((c & 0x07ffffffff) << 5) ^ value
        if c0 & 0x01: c ^= 0x98f2bc8e61
        if c0 & 0x02: c ^= 0x79b76d99e2
        if c0 & 0x04: c ^= 0xf33e5fb3c4
        if c0 & 0x08: c ^= 0xae2eabe2a8
        if c0 & 0x10: c ^= 0x1e4f43e470
    return c ^ 1


def cashaddr_encode(hrp, payload):
    """Encode payload to CashAddr format."""
    # Convert payload to 5-bit groups
    data = convertbits(payload, 8, 5)
    if data is None:
        raise ValueError("Failed to convert bits")
    
    # Expand HRP
    hrp_expanded = [ord(x) & 0x1f for x in hrp] + [0]
    
    # Calculate checksum
    values = hrp_expanded + data + [0, 0, 0, 0, 0, 0, 0, 0]
    polymod = cashaddr_polymod(values)
    checksum = [(polymod >> (5 * (7 - i))) & 0x1f for i in range(8)]
    
    # Encode
    charset = 'qpzry9x8gf2tvdw0s3jn54khce6mua7l'
    return hrp + ':' + ''.join([charset[d] for d in data + checksum])


def keccak256(data: bytes) -> bytes:
    from Crypto.Hash import keccak as _keccak
    k = _keccak.new(digest_bits=256)
    k.update(data)
    return k.digest()


def eth_checksum_address(addr_bytes: bytes) -> str:
    """EIP-55 checksum encoding."""
    hex_addr = addr_bytes.hex()
    h = keccak256(hex_addr.encode()).hex()
    return "0x" + "".join(
        c.upper() if int(h[i], 16) >= 8 else c
        for i, c in enumerate(hex_addr)
    )


def public_key_to_address(pubkey: bytes, currency: str, addr_type: str) -> str:
    if currency not in ("btc", "testnet4", "ltc", "tltc", "bch", "tbch", "eth", "teth"):
        raise ValueError(f"Unsupported currency: {currency}")

    if currency in ("eth", "teth"):
        # Decompress if needed, then use uncompressed X||Y for keccak
        from ecdsa import SECP256k1, VerifyingKey
        if len(pubkey) == 33:
            vk = VerifyingKey.from_string(pubkey, curve=SECP256k1)
            uncompressed = vk.to_string()  # 64 bytes X||Y
        else:
            uncompressed = pubkey[1:] if pubkey[0] == 0x04 else pubkey
        addr_bytes = keccak256(uncompressed)[12:]
        return eth_checksum_address(addr_bytes)

    if addr_type == "p2pkh":
        # Standard P2PKH version bytes
        versions = {
            "btc": b'\x00',      # Bitcoin Mainnet (1...)
            "testnet4": b'\x6f', # Bitcoin Testnet (m/n...)
            "ltc": b'\x30',      # Litecoin Mainnet (L...)
            "tltc": b'\x6f',     # Litecoin Testnet
            "bch": b'\x00',      # Bitcoin Cash legacy (1...)
            "tbch": b'\x6f'      # Bitcoin Cash Testnet legacy
        }
        version = versions[currency]
        
        hash160_pub = hash160(pubkey)
        
        # Bitcoin Cash uses CashAddr format
        if currency in ("bch", "tbch"):
            hrp = "bitcoincash" if currency == "bch" else "bchtest"
            # Version byte: 0x00 for P2PKH
            payload = bytes([0x00]) + hash160_pub
            return cashaddr_encode(hrp, payload)
        else:
            # Legacy Base58 encoding for BTC/LTC
            version_hash = version + hash160_pub
            checksum = hashlib.sha256(hashlib.sha256(version_hash).digest()).digest()[:4]
            return base58.b58encode(version_hash + checksum).decode()

    elif addr_type in ("p2wpkh", "bip-84"):
        # Native SegWit addresses
        hrps = {
            "btc": "bc",
            "testnet4": "tb",
            "ltc": "ltc",
            "tltc": "tltc"
        }
        
        # BCH does not support native SegWit
        if currency in ("bch", "tbch"):
            raise ValueError(f"Bitcoin Cash does not support SegWit addresses. Use p2pkh instead.")
        
        hrp = hrps[currency]
        hash160_pub = hash160(pubkey)
        witness_program = convertbits(hash160_pub, 8, 5)
        return bech32_encode(hrp, [0] + witness_program)

    else:
        raise ValueError(f"Unsupported address type: {addr_type}")


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Derive a child address and add it to a wallet")
    parser.add_argument("name", help="Wallet name")
    parser.add_argument("path", help="BIP32 derivation path, e.g. m/84'/0'/0'/0/0")
    parser.add_argument("currency", help="Currency (btc, testnet4, ltc, bch, tbch, eth, teth)")
    parser.add_argument("type", help="Address type (p2pkh, p2wpkh, bip-84; ignored for eth/teth)")
    parser.add_argument("password_parent", help="Password used to decrypt the parent key")
    parser.add_argument("password_address", help="Password used to encrypt the derived address key")
    parser.add_argument("--comment", help="Optional comment for the derived address", default="")
    return parser.parse_args()


def main() -> None:
    args = _parse_args()

    print("--- CONFIG ---")
    print(f"  Wallet   : {args.name}")
    print(f"  Path     : {args.path}")
    print(f"  Currency : {args.currency}")
    print(f"  Type     : {args.type}")
    print(f"  Passwords: suppressed")
    print()

    wallet_file = os.path.join("..", "wallets", args.name + ".json")
    print(f"Loading wallet: {wallet_file}")
    try:
        with open(wallet_file, "r") as f:
            wallet_data = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError) as e:
        raise ValueError(f"Unable to load wallet file {wallet_file}: {e}") from e

    wallet = wallet_data.get("wallet", {})
    parents = wallet.get("parents", [])
    matched_parent = None
    parent_path = None

    print("Searching for matching parent key...")
    for parent in parents:
        parent_components = parent["path"].split("/")
        args_components = args.path.split("/")
        if len(parent_components) < len(args_components) and args.path.startswith(parent["path"]):
            if matched_parent is None or len(parent_components) > len(parent_path.split("/")):
                matched_parent = parent
                parent_path = parent["path"]
                print(f"  Found parent: {parent_path}")

    if matched_parent is None:
        comps = args.path.split("/")
        suggested_parent = "/".join(comps[:-1]) if len(comps) > 1 else args.path
        print(f"\nERROR: No matching parent entry found in wallet.")
        print(f"Please create a parent key first:")
        print(f"  python makeparent.py {args.name} {suggested_parent} <password_root> <password_parent>")
        print()
        raise ValueError("Parent entry required. Please run makeparent.py first.")

    parent_priv_enc = bytes.fromhex(matched_parent["private-key-enc"])
    parent_chaincode = bytes.fromhex(matched_parent["chaincode"])

    print("Decrypting parent key...")
    try:
        parent_priv = decrypt_private_key(parent_priv_enc, args.password_parent)
    except Exception as exc:
        raise ValueError("Unable to decrypt parent private key - bad parent password?") from exc

    rel_path = args.path
    if parent_path and rel_path.startswith(parent_path + "/"):
        rel_path = rel_path[len(parent_path) + 1:]
    elif rel_path == parent_path:
        rel_path = ""

    if rel_path:
        # derive_path requires a full BIP32 path starting with 'm/'
        full_rel_path = "m/" + rel_path
        print(f"Deriving relative path: {full_rel_path}")
        child_priv, _ = derive_path(parent_priv, parent_chaincode, full_rel_path)
    else:
        # parent key IS the target — no further derivation needed
        print("Deriving relative path: (none, using parent key directly)")
        child_priv = parent_priv
        
    pubkey = private_key_to_public_key(child_priv)
    address = public_key_to_address(pubkey, args.currency, args.type)
    print(f"Derived address: {address}")

    entry = {
        "path": args.path,
        "public-key": pubkey.hex(),
        "currency": args.currency,
        "type": args.type,
        "address": address,
        "private-key-enc": encrypt_private_key(child_priv, args.password_address).hex(),
        "comment": args.comment or ""
    }

    if args.currency in ("eth", "teth"):
        entry["balance"] = 0
        entry["nonce"] = 0
        entry["transactions"] = []
    else:
        entry["UTXO"] = []
        entry["transactions"] = []

    if wallet_data["wallet"].get("addresses") is None:
        wallet_data["wallet"]["addresses"] = []

    for existing in wallet_data["wallet"]["addresses"]:
        if existing["path"] == args.path and existing["address"] == address:
            raise ValueError(f"Address entry for path {args.path} already exists in wallet.")

    wallet_data["wallet"]["addresses"].append(entry)

    with open(wallet_file, "w") as f:
        json.dump(wallet_data, f, indent=2)

    print(f"OK: Added address at {args.path} to {wallet_file}")


if __name__ == "__main__":
    main()
