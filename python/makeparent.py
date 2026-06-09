"""Parent key derivation utility for hash-wallet.

This tool reads the master key from an existing wallet JSON file, decrypts it
with a password, derives a parent private key using the supplied BIP32 path,
and stores the parent entry in the wallet. The parent key and its chaincode
are encrypted with a second password for later use when deriving address keys.
"""

import argparse
import json
import os
from pathlib import Path
import sys

sys.path.append(str(Path(__file__).resolve().parent.parent))

from assets.crypto_utils import encrypt_private_key, decrypt_private_key
from assets.bip32_utils import derive_path, private_key_to_public_key


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Derive a parent key for a wallet")
    parser.add_argument("name", help="Wallet name")
    parser.add_argument("path", help="BIP32 derivation path for the parent key, e.g. m/84'/0'/0'/0")
    parser.add_argument("password_root", help="Password used to decrypt the master private key")
    parser.add_argument("password_parent", help="Password used to encrypt the derived parent key")
    return parser.parse_args()


def main() -> None:
    args = _parse_args()

    print("--- CONFIG ---")
    print(f"  Wallet   : {args.name}")
    print(f"  Path     : {args.path}")
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
    master_entry = wallet.get("master")
    if master_entry is None:
        raise ValueError("Wallet file does not contain wallet.master")

    master_priv_enc = bytes.fromhex(master_entry["private-key-enc"])
    master_chaincode = bytes.fromhex(master_entry["chaincode"])

    print("Decrypting master key...")
    try:
        master_priv = decrypt_private_key(master_priv_enc, args.password_root)
    except Exception as exc:
        raise ValueError("Unable to decrypt master private key - bad root password?") from exc

    print(f"Deriving path: {args.path}")
    child_priv, child_chaincode = derive_path(master_priv, master_chaincode, args.path)

    pubkey = private_key_to_public_key(child_priv)
    entry = {
        "path": args.path,
        "public-key": pubkey.hex(),
        "chaincode": child_chaincode.hex(),
        "private-key-enc": encrypt_private_key(child_priv, args.password_parent).hex(),
    }

    if wallet_data["wallet"].get("parents") is None:
        wallet_data["wallet"]["parents"] = []

    wallet_data["wallet"]["parents"].append(entry)

    with open(wallet_file, "w") as f:
        json.dump(wallet_data, f, indent=2)

    print(f"OK: Added parent at {args.path} to {wallet_file}")


if __name__ == "__main__":
    main()
