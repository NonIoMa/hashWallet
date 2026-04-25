"""Master wallet creation utility for hash-wallet.

Generates a new wallet JSON file from either a raw 64-byte seed or a BIP39
mnemonic phrase. Derives the BIP32 master private key and chaincode, encrypts
the master key with a password using AES-256-GCM, and writes the result to
a wallet file under ../wallets/<name>.json.

Usage:
    python makewallet.py <name> -m <24 words> [--passphrase <phrase>] [<password>] [-p privacy] [-r]
    python makewallet.py <name> -s <hex_seed> [<password>] [-p privacy] [-r]
"""

import os
import json
import hmac
import argparse
import hashlib
import getpass
from pathlib import Path
import sys

from mnemonic import Mnemonic
from ecdsa import SECP256k1, SigningKey
from ecdsa.util import number_to_string

sys.path.append(str(Path(__file__).resolve().parent.parent))

from assets.crypto_utils import encrypt_private_key


# --- Key Utilities ---

BITCOIN_SEED = b"Bitcoin seed"


def private_key_to_public_key(privkey: bytes, curve_order: int) -> bytes:
    """Convert a private key to a compressed public key."""
    sk = SigningKey.from_string(privkey, curve=SECP256k1)
    vk = sk.get_verifying_key()
    prefix = b'\x02' if vk.pubkey.point.y() % 2 == 0 else b'\x03'
    return prefix + number_to_string(vk.pubkey.point.x(), curve_order)


def mnemonic_to_seed(mnemonic_phrase: str, passphrase: str = "") -> bytes:
    """Convert a BIP39 mnemonic phrase to a 64-byte seed using PBKDF2."""
    mnemo = Mnemonic("english")
    if not mnemo.check(mnemonic_phrase):
        raise ValueError("Invalid mnemonic phrase")
    return mnemo.to_seed(mnemonic_phrase, passphrase)


def seed_to_master_key(seed: bytes) -> tuple[bytes, bytes]:
    """Derive BIP32 master private key and chaincode from a seed."""
    I = hmac.new(BITCOIN_SEED, seed, hashlib.sha512).digest()
    return I[:32], I[32:]


# --- Wallet File ---

def write_wallet_data(name, private_key_enc_bytes, chaincode, public_key, privacy, reset):
    """Write the master key entry to the wallet JSON file.

    Creates the file if it does not exist. If ``reset`` is True, overwrites
    any existing content.
    """
    wallet_file = os.path.join("..", "wallets", name + ".json")

    if not os.path.exists(wallet_file) or reset:
        data = {"wallet": {}}
    else:
        try:
            with open(wallet_file, "r") as f:
                data = json.load(f)
        except json.JSONDecodeError as e:
            raise ValueError(f"Invalid JSON in wallet file {wallet_file}: {e}") from e
        if not isinstance(data, dict):
            raise ValueError(f"Wallet file {wallet_file} does not contain a JSON object")
        if "wallet" not in data:
            data["wallet"] = {}

    data["wallet"]["master"] = {
        "private-key-enc": private_key_enc_bytes.hex(),
        "chaincode": chaincode.hex(),
        "public-key": public_key.hex(),
        "privacy": privacy,
    }

    with open(wallet_file, "w") as f:
        json.dump(data, f, indent=2)

    print(f"OK: Wallet written to {wallet_file}")


# --- CLI ---

def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Create a new hash-wallet JSON file")
    parser.add_argument("name", help="Wallet name")
    parser.add_argument(
        "-s", "--seed", type=lambda s: bytes.fromhex(s),
        help="Seed as hex string (128 hex chars = 64 bytes)")
    parser.add_argument(
        "-m", "--mnemonic", nargs='+',
        help="BIP39 mnemonic phrase (24 words, space separated)")
    parser.add_argument(
        "--passphrase", default="",
        help="Optional BIP39 passphrase (default: empty)")
    parser.add_argument(
        "password", nargs='?',
        help="Master key encryption password (will prompt if omitted)")
    parser.add_argument(
        "-p", "--privacy", type=int, default=1,
        help="Privacy level: 0 = heavy, 1 = light, 2 = none (default: 1)")
    parser.add_argument(
        "-r", "--reset", action="store_true",
        help="Overwrite the wallet file if it already exists")
    args = parser.parse_args()

    if args.seed is None and args.mnemonic is None:
        parser.error("Either --seed or --mnemonic is required")
    if args.seed is not None and args.mnemonic is not None:
        parser.error("Cannot specify both --seed and --mnemonic")
    if args.seed is not None and len(args.seed) != 64:
        parser.error("Seed must be exactly 64 bytes (128 hex characters)")
    if args.password is None:
        args.password = getpass.getpass("Enter encryption password: ")

    return args


def main() -> None:
    args = _parse_args()

    print("--- CONFIG ---")
    print(f"  Wallet   : {args.name}")
    if args.mnemonic:
        print(f"  Mnemonic : {'*' * len(' '.join(args.mnemonic))}")
        print(f"  Passphrase: {'(set)' if args.passphrase else '(none)'}")
    else:
        print(f"  Seed     : {args.seed.hex()[:16]}...")
    print(f"  Privacy  : {args.privacy} ({'heavy' if args.privacy == 0 else 'light' if args.privacy == 1 else 'none'})")
    print(f"  Reset    : {'yes' if args.reset else 'no'}")
    print(f"  Password : suppressed")
    print()

    if args.mnemonic:
        print("Deriving seed from mnemonic...")
        seed = mnemonic_to_seed(' '.join(args.mnemonic), args.passphrase)
    else:
        seed = args.seed

    print("Deriving master key...")
    private_key, chaincode = seed_to_master_key(seed)
    public_key = private_key_to_public_key(private_key, SECP256k1.order)

    print("Encrypting master key...")
    private_key_enc_result = encrypt_private_key(private_key, args.password)

    write_wallet_data(args.name, private_key_enc_result, chaincode, public_key, args.privacy, args.reset)


if __name__ == "__main__":
    main()
